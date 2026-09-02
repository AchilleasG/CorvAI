from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from coding.auth import CodexDeviceAuthService
from coding.browser_runner import INTERACTIVE_ACTIONS, InteractiveBrowserSession
from coding.models import CodingSession, CodingTurn, FeatureDelegation, FeatureQaRun
from coding.services import CodingSessionService, MAX_EVENT_LOG_CHARS


ACTIVE_DELEGATION_STATUSES = [
    FeatureDelegation.STATUS_QUEUED,
    FeatureDelegation.STATUS_CODING,
    FeatureDelegation.STATUS_QA,
    FeatureDelegation.STATUS_FIXING,
]


class FeatureDelegationService:
    _active: set[str] = set()
    _qa_processes: dict[str, subprocess.Popen] = {}
    _lock = threading.RLock()

    @staticmethod
    def _notify(delegation: FeatureDelegation, event: str, body: str):
        from orchestration.notifications import send_coding_push_to_all

        try:
            send_coding_push_to_all(
                title=f"Feature · {delegation.title}",
                body=(body or "Feature delegation update")[:500],
                session_id=str(delegation.session_id),
                delegation_id=str(delegation.pk),
                event=event,
            )
        except Exception:
            pass
        try:
            from coding.chat_waits import CodingChatWaitService
            delegation.refresh_from_db()
            CodingChatWaitService.publish_for_delegation(delegation)
        except Exception:
            pass

    @classmethod
    def create(
        cls,
        session: CodingSession,
        *,
        title: str,
        description: str,
        acceptance_criteria: list[str],
        qa_enabled: bool = True,
        max_iterations: int = 6,
        file_ids=None,
    ) -> FeatureDelegation:
        if not CodexDeviceAuthService._is_authenticated():
            raise ValueError("Configure the selected Codex authentication method in Settings")
        if session.status == CodingSession.STATUS_STOPPED:
            raise ValueError("This coding session has been stopped")
        if CodingSessionService.tmux_alive(session):
            raise ValueError("Close the direct Codex CLI before starting a feature delegation")
        if session.delegations.filter(
            status__in=[*ACTIVE_DELEGATION_STATUSES, FeatureDelegation.STATUS_NEEDS_INPUT]
        ).exists():
            raise ValueError("This coding session already has an active feature delegation")
        criteria = [str(item).strip() for item in acceptance_criteria if str(item).strip()]
        if not title.strip() or not description.strip() or not criteria:
            raise ValueError("Title, description, and at least one acceptance criterion are required")
        if file_ids:
            from coding.files import resolve_files
            resolve_files(file_ids, session=session)
        delegation = FeatureDelegation.objects.create(
            session=session,
            title=title.strip(),
            description=description.strip(),
            acceptance_criteria=criteria,
            qa_enabled=bool(qa_enabled),
            max_iterations=max(1, min(int(max_iterations), 12)),
        )
        if file_ids:
            from coding.files import materialize_inputs
            paths = materialize_inputs(session, file_ids)
            ManagedFile.objects.filter(pk__in=file_ids).update(delegation=delegation)
            delegation.description += "\n\nAttached input files (read these as part of the request):\n" + "\n".join(f"- {path}" for path in paths)
            delegation.save(update_fields=["description", "updated_at"])
        cls._spawn(delegation)
        return delegation

    @classmethod
    def _spawn(
        cls,
        delegation: FeatureDelegation,
        continuation: str = "",
        *,
        qa_only: bool = False,
    ):
        key = str(delegation.pk)
        with cls._lock:
            if key in cls._active:
                raise ValueError("This feature delegation is already running")
            cls._active.add(key)
        threading.Thread(
            target=cls._run_loop,
            args=(key, continuation, qa_only),
            daemon=True,
        ).start()

    @classmethod
    def _is_stopped(cls, delegation_id: str) -> bool:
        return FeatureDelegation.objects.filter(
            pk=delegation_id, status=FeatureDelegation.STATUS_STOPPED
        ).exists()

    @classmethod
    def _wait_for_coder_turn(cls, delegation_id: str, turn: CodingTurn) -> CodingTurn:
        while True:
            close_old_connections()
            if cls._is_stopped(delegation_id):
                CodingSessionService.cancel_turn(turn)
                turn.refresh_from_db()
                return turn
            turn.refresh_from_db()
            if turn.status not in [CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING]:
                return turn
            time.sleep(0.5)

    @staticmethod
    def _criteria_text(delegation: FeatureDelegation) -> str:
        return "\n".join(
            f"{index}. {criterion}"
            for index, criterion in enumerate(delegation.acceptance_criteria, start=1)
        )

    @classmethod
    def _coder_prompt(cls, delegation: FeatureDelegation, continuation: str = "") -> str:
        if delegation.current_iteration <= 1:
            context = "Implement this feature completely."
        else:
            latest_qa = delegation.qa_runs.order_by("-started_at").first()
            failures = "\n".join(f"- {item}" for item in (latest_qa.failures if latest_qa else []))
            context = (
                "Resume the same implementation and fix every issue found by the independent QA bot.\n"
                f"QA summary: {delegation.qa_summary}\nFailures:\n{failures or '- Review the QA summary and evidence.'}"
            )
        if continuation:
            context += f"\n\nUser/Corv continuation decision:\n{continuation}"
        public_base = str(getattr(settings, "CORV_PUBLIC_BASE_URL", "") or "").rstrip("/")
        artifact_url = f"{public_base}/api/files/delegations/{delegation.pk}/upload"
        artifact_instruction = (
            f"Upload every requested file artifact with multipart field 'file' to {artifact_url}. "
            "The delegation UUID associates it with this coding session and makes it visible to the user. "
            "You may upload artifacts as soon as they are ready."
            if public_base else
            f"Requested file artifacts must be uploaded through /api/files/delegations/{delegation.pk}/upload "
            "using multipart field 'file' once the Corv public API base URL is available."
        )
        return f"""Feature delegation: {delegation.title}

Description:
{delegation.description}

Acceptance criteria:
{cls._criteria_text(delegation)}

{context}

File artifacts:
{artifact_instruction}

Do not stop after analysis. Inspect the existing remote repository, implement the work, run relevant tests, and verify it. Continue autonomously unless a material product decision or external blocker truly requires the user.
"""

    @classmethod
    def _qa_prompt(
        cls,
        delegation: FeatureDelegation,
        qa_run: FeatureQaRun,
        continuation: str = "",
    ) -> str:
        evidence_dir = CodingSessionService.workspace_dir(delegation.session) / "qa-evidence" / str(qa_run.pk)
        continuation_block = (
            f"\nUser/Corv instruction for this QA retry:\n{continuation}\n"
            if continuation.strip()
            else ""
        )
        return f"""You are the independent QA bot for this feature. Do not edit application code.

Feature: {delegation.title}
Description: {delegation.description}
Acceptance criteria:
{cls._criteria_text(delegation)}

Coder's latest report:
{delegation.implementation_summary}
{continuation_block}

Work on the same configured SSH target. Inspect the actual diff and repository state, run focused and regression tests, and independently verify every acceptance criterion. Do not accept the coder's report without evidence.

Corv provides a persistent interactive Chrome browser. For any browser-accessible UI or user flow, you MUST test it interactively before passing it. Do not use ./qa-browser directly. Instead, return status "action" with exactly one browser action. Corv will execute it and resume you with a screenshot, visible page text, available controls, URL, and browser-console output. Examine every screenshot and page observation before choosing the next action, just as a user would.

Start with action type "start" and the real application URL. If the app is bound to localhost on the SSH target, set tunnel_local_port and tunnel_remote_port, browse through 127.0.0.1:tunnel_local_port, and let Corv maintain the tunnel. Then proceed one meaningful action at a time: click, fill, press, select, scroll, navigate, wait, or assert. Use stable CSS selectors from the supplied interactive-elements list where possible. Exercise the complete happy path and relevant failure states, inspect console errors, and capture evidence at every step. The evidence directory is {evidence_dir}.

For a final verdict, use action type "none". Set browser_applicable truthfully. If browser_applicable is true, you may not return passed until you have used the interactive browser and demonstrated the applicable acceptance criteria. A build, unit test, source inspection, or loaded landing page alone is not end-to-end evidence.

Before returning passed for a browser-applicable feature, either perform at least one successful assert_visible, assert_text, or assert_url_contains action, or complete meaningful successful interactions such as filling and submitting a form, navigating the tested flow, or operating the changed controls. Merely starting the browser or taking a screenshot is insufficient.

Return passed only when all acceptance criteria are demonstrated. Return failed with concrete reproducible failures when the coder should fix the work. Return blocked only for an external dependency or user decision that testing cannot resolve.
"""

    @staticmethod
    def _browser_followup_prompt(observation: dict, step: int, max_steps: int) -> str:
        compact = {
            "success": observation.get("success"),
            "error": observation.get("error"),
            "step": observation.get("step"),
            "url": observation.get("url"),
            "title": observation.get("title"),
            "visible_text": observation.get("visible_text"),
            "interactive_elements": observation.get("interactive_elements"),
            "console": observation.get("console"),
        }
        return f"""Interactive browser observation after step {step} of at most {max_steps}:

{json.dumps(compact, ensure_ascii=False)}

The current screenshot is attached. Inspect both the screenshot and structured page state. Decide the single next browser action, or return the final QA verdict. Continue through the real user flow; do not pass based only on page load or source inspection. If an action failed, use the observation to recover when possible before declaring a reproducible failure.
"""

    @classmethod
    def _qa_command(
        cls,
        codex: str,
        workspace: Path,
        thread_id: str,
        images: list[str] | None = None,
    ) -> list[str]:
        options = [
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--json",
            "--output-schema",
            str(workspace / "qa-result-schema.json"),
        ]
        for image in images or []:
            options.extend(["--image", image])
        if thread_id:
            return [codex, "exec", "resume", *options, thread_id, "-"]
        return [codex, "exec", *options, "-C", str(workspace), "-"]

    @classmethod
    def _execute_qa_turn(
        cls,
        delegation: FeatureDelegation,
        qa_run: FeatureQaRun,
        prompt: str,
        images: list[str] | None = None,
    ) -> tuple[dict, str, list[str]]:
        workspace, environment = CodingSessionService.prepare_workspace(delegation.session)
        from coding.auth import CodexAuthService

        environment = CodexAuthService.process_environment(environment)
        codex = shutil.which("codex")
        if not codex:
            raise RuntimeError("Codex CLI is not installed")
        command = cls._qa_command(codex, workspace, delegation.qa_thread_id, images)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=workspace,
            env=environment,
            start_new_session=True,
        )
        key = str(qa_run.pk)
        with cls._lock:
            cls._qa_processes[key] = process
        log_lines: list[str] = []
        base_log = qa_run.event_log
        live_log = ""
        final_message = ""
        thread_id = delegation.qa_thread_id
        try:
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.close()
            assert process.stdout is not None
            for raw_line in process.stdout:
                if cls._is_stopped(str(delegation.pk)):
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                line = raw_line.rstrip("\n")
                live_log = f"{live_log}\n{line}".lstrip("\n")[-MAX_EVENT_LOG_CHARS:]
                log_lines = live_log.splitlines()
                qa_run.event_log = "\n".join(
                    item for item in [base_log, live_log] if item
                )[-MAX_EVENT_LOG_CHARS:]
                FeatureQaRun.objects.filter(pk=qa_run.pk).update(event_log=qa_run.event_log)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "thread.started" and event.get("thread_id"):
                    thread_id = str(event["thread_id"])
                    FeatureDelegation.objects.filter(pk=delegation.pk).update(qa_thread_id=thread_id)
                    delegation.qa_thread_id = thread_id
                item = event.get("item") or {}
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    final_message = str(item.get("text") or "")
            return_code = process.wait()
            if cls._is_stopped(str(delegation.pk)):
                raise RuntimeError("Feature delegation was stopped")
            if return_code != 0:
                raise RuntimeError(log_lines[-1] if log_lines else f"QA Codex exited with status {return_code}")
            try:
                result = json.loads(final_message)
            except (ValueError, TypeError) as exc:
                raise RuntimeError("QA bot returned an invalid structured result") from exc
            return result, thread_id, log_lines
        finally:
            with cls._lock:
                cls._qa_processes.pop(key, None)

    @classmethod
    def _run_qa(cls, delegation: FeatureDelegation, continuation: str = "") -> FeatureQaRun:
        qa_run = FeatureQaRun.objects.create(
            delegation=delegation,
            iteration=delegation.current_iteration,
        )
        log_lines: list[str] = []
        browser = None
        screenshots: list[str] = []
        browser_actions: list[str] = []
        successful_browser_assertions = 0
        successful_browser_interactions = 0
        max_browser_steps = 60
        try:
            result, thread_id, first_log = cls._execute_qa_turn(
                delegation,
                qa_run,
                cls._qa_prompt(delegation, qa_run, continuation),
            )
            log_lines.extend(first_log)
            evidence_dir = CodingSessionService.workspace_dir(delegation.session) / "qa-evidence" / str(qa_run.pk)
            while str(result.get("status") or "") == "action":
                if len(browser_actions) >= max_browser_steps:
                    result = {
                        "status": "blocked",
                        "summary": "Interactive browser QA reached its safety step limit.",
                        "failures": [],
                        "evidence": [],
                        "question": "QA used 60 browser actions without reaching a verdict. Review the flow or allow a new QA run.",
                        "options": ["Resume QA", "Stop the delegation"],
                        "browser_applicable": True,
                        "action": {"type": "none"},
                    }
                    break
                action = result.get("action") or {}
                action_type = str(action.get("type") or "").strip().lower()
                if action_type not in INTERACTIVE_ACTIONS:
                    result = {
                        "status": "failed",
                        "summary": "QA returned an invalid interactive browser action.",
                        "failures": [f"Unsupported browser action: {action_type or '(empty)'}"],
                        "evidence": [],
                        "question": "",
                        "options": [],
                        "browser_applicable": True,
                        "action": {"type": "none"},
                    }
                    break
                if browser is None:
                    browser = InteractiveBrowserSession(
                        evidence_dir,
                        workspace_dir=CodingSessionService.workspace_dir(delegation.session),
                    )
                observation = browser.perform(action)
                browser_actions.append(action_type)
                if observation.get("success") and action_type in {
                    "assert_visible", "assert_text", "assert_url_contains"
                }:
                    successful_browser_assertions += 1
                if observation.get("success") and action_type in {
                    "goto", "click", "fill", "press", "select", "scroll", "back", "refresh"
                }:
                    successful_browser_interactions += 1
                screenshot = str(observation.get("screenshot") or "")
                if screenshot:
                    screenshots.append(screenshot)
                browser_event = json.dumps(
                    {
                        "type": "browser.action.completed",
                        "action": action_type,
                        "success": bool(observation.get("success")),
                        "step": observation.get("step"),
                        "url": observation.get("url"),
                        "error": observation.get("error"),
                        "screenshot": screenshot,
                    },
                    ensure_ascii=False,
                )
                log_lines.append(browser_event)
                qa_run.event_log = "\n".join(log_lines)[-MAX_EVENT_LOG_CHARS:]
                FeatureQaRun.objects.filter(pk=qa_run.pk).update(event_log=qa_run.event_log)
                result, thread_id, visual_log = cls._execute_qa_turn(
                    delegation,
                    qa_run,
                    cls._browser_followup_prompt(
                        observation, len(browser_actions), max_browser_steps
                    ),
                    [screenshot] if screenshot else None,
                )
                log_lines.extend(visual_log)

            if (
                str(result.get("status") or "") == "passed"
                and bool(result.get("browser_applicable"))
                and (
                    not browser_actions
                    or (
                        successful_browser_assertions == 0
                        and successful_browser_interactions == 0
                    )
                )
            ):
                result = {
                    **result,
                    "status": "failed",
                    "summary": "QA attempted to pass a browser-accessible feature without verified interactive browser evidence.",
                    "failures": [
                        "Browser-applicable QA requires a persistent browser flow with a successful rendered-state assertion or meaningful interaction."
                    ],
                }
            status = str(result.get("status") or "failed")
            qa_run.status = {
                "passed": FeatureQaRun.STATUS_PASSED,
                "blocked": FeatureQaRun.STATUS_BLOCKED,
            }.get(status, FeatureQaRun.STATUS_FAILED)
            qa_run.summary = str(result.get("summary") or "").strip()
            qa_run.failures = [str(item) for item in (result.get("failures") or [])][:50]
            reported_evidence = [str(item) for item in (result.get("evidence") or [])][:100]
            qa_run.evidence = list(dict.fromkeys(reported_evidence + screenshots))[:100]
            qa_run.question = str(result.get("question") or "").strip()
            qa_run.options = [str(item) for item in (result.get("options") or [])][:10]
            qa_run.event_log = "\n".join(log_lines)[-MAX_EVENT_LOG_CHARS:]
            qa_run.completed_at = timezone.now()
            qa_run.save(
                update_fields=[
                    "status", "summary", "failures", "evidence", "question", "options",
                    "event_log", "completed_at",
                ]
            )
        except Exception as exc:
            qa_run.status = FeatureQaRun.STATUS_ERROR
            qa_run.error = str(exc)
            qa_run.event_log = "\n".join(log_lines)[-MAX_EVENT_LOG_CHARS:]
            qa_run.completed_at = timezone.now()
            qa_run.save(update_fields=["status", "error", "event_log", "completed_at"])
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
        return qa_run

    @classmethod
    def _run_loop(
        cls,
        delegation_id: str,
        continuation: str = "",
        qa_only: bool = False,
    ):
        close_old_connections()
        try:
            while True:
                delegation = FeatureDelegation.objects.select_related("session__machine").get(pk=delegation_id)
                if delegation.status == FeatureDelegation.STATUS_STOPPED:
                    return
                qa_continuation = continuation if qa_only else ""
                if qa_only:
                    qa_only = False
                    continuation = ""
                else:
                    if delegation.current_iteration >= delegation.max_iterations:
                        delegation.status = FeatureDelegation.STATUS_NEEDS_INPUT
                        delegation.pending_question = (
                            f"QA is still not passing after {delegation.current_iteration} implementation cycles. "
                            "Should Codex continue with three more fix-and-test cycles?"
                        )
                        delegation.pending_options = ["Continue for three more cycles", "Stop the delegation"]
                        delegation.save(update_fields=["status", "pending_question", "pending_options", "updated_at"])
                        CodingSession.objects.filter(pk=delegation.session_id).update(
                            status=CodingSession.STATUS_NEEDS_INPUT,
                            pending_question="",
                            pending_options=[],
                        )
                        cls._notify(delegation, "needs_input", delegation.pending_question)
                        return

                    delegation.current_iteration += 1
                    delegation.status = (
                        FeatureDelegation.STATUS_CODING
                        if delegation.current_iteration == 1
                        else FeatureDelegation.STATUS_FIXING
                    )
                    delegation.pending_question = ""
                    delegation.pending_options = []
                    delegation.last_error = ""
                    delegation.save(
                        update_fields=[
                            "current_iteration", "status", "pending_question", "pending_options",
                            "last_error", "updated_at",
                        ]
                    )
                    turn = CodingSessionService.start_turn(
                        delegation.session,
                        cls._coder_prompt(delegation, continuation),
                        source=CodingTurn.SOURCE_FEATURE,
                    )
                    continuation = ""
                    delegation.coding_turn_ids = [*delegation.coding_turn_ids, str(turn.pk)]
                    delegation.save(update_fields=["coding_turn_ids", "updated_at"])
                    turn = cls._wait_for_coder_turn(delegation_id, turn)
                    if cls._is_stopped(delegation_id):
                        return
                    if turn.status == CodingTurn.STATUS_NEEDS_INPUT:
                        FeatureDelegation.objects.filter(pk=delegation_id).update(
                            status=FeatureDelegation.STATUS_NEEDS_INPUT,
                            implementation_summary=turn.summary,
                            pending_question=turn.question,
                            pending_options=turn.options,
                        )
                        CodingSession.objects.filter(pk=delegation.session_id).update(
                            status=CodingSession.STATUS_NEEDS_INPUT,
                            pending_question="",
                            pending_options=[],
                        )
                        cls._notify(delegation, "needs_input", turn.question or "Codex needs your decision.")
                        return
                    if turn.status != CodingTurn.STATUS_COMPLETED:
                        FeatureDelegation.objects.filter(pk=delegation_id).update(
                            status=FeatureDelegation.STATUS_FAILED,
                            last_error=turn.error or "The coding turn failed",
                        )
                        cls._notify(
                            delegation,
                            "failed",
                            turn.error or "The coding turn failed and needs attention.",
                        )
                        return
                    delegation.implementation_summary = turn.summary
                    delegation.save(update_fields=["implementation_summary", "updated_at"])
                    if not delegation.qa_enabled:
                        delegation.status = FeatureDelegation.STATUS_COMPLETED
                        delegation.completed_at = timezone.now()
                        delegation.save(update_fields=["status", "completed_at", "updated_at"])
                        CodingSession.objects.filter(pk=delegation.session_id).update(status=CodingSession.STATUS_READY)
                        cls._notify(
                            delegation,
                            "completed",
                            turn.summary or "The feature implementation is complete.",
                        )
                        return

                delegation.status = FeatureDelegation.STATUS_QA
                delegation.save(update_fields=["status", "updated_at"])
                CodingSession.objects.filter(pk=delegation.session_id).update(status=CodingSession.STATUS_RUNNING)
                qa_run = cls._run_qa(delegation, qa_continuation)
                if cls._is_stopped(delegation_id):
                    return
                delegation.refresh_from_db()
                delegation.qa_summary = qa_run.summary
                if qa_run.status == FeatureQaRun.STATUS_PASSED:
                    delegation.status = FeatureDelegation.STATUS_COMPLETED
                    delegation.completed_at = timezone.now()
                    delegation.save(update_fields=["status", "qa_summary", "completed_at", "updated_at"])
                    CodingSession.objects.filter(pk=delegation.session_id).update(status=CodingSession.STATUS_READY)
                    cls._notify(
                        delegation,
                        "completed",
                        qa_run.summary or "Implementation and independent QA are complete.",
                    )
                    return
                if qa_run.status in [FeatureQaRun.STATUS_BLOCKED, FeatureQaRun.STATUS_ERROR]:
                    delegation.status = FeatureDelegation.STATUS_NEEDS_INPUT
                    delegation.pending_question = qa_run.question or qa_run.error or "QA is blocked and needs direction."
                    delegation.pending_options = qa_run.options
                    delegation.last_error = qa_run.error
                    delegation.save(
                        update_fields=[
                            "status", "qa_summary", "pending_question", "pending_options",
                            "last_error", "updated_at",
                        ]
                    )
                    CodingSession.objects.filter(pk=delegation.session_id).update(
                        status=CodingSession.STATUS_NEEDS_INPUT,
                        pending_question="",
                        pending_options=[],
                    )
                    cls._notify(delegation, "needs_input", delegation.pending_question)
                    return
                delegation.save(update_fields=["qa_summary", "updated_at"])
                # A reproducible QA failure is automatically fed into the next coder turn.
        except Exception as exc:
            if not cls._is_stopped(delegation_id):
                FeatureDelegation.objects.filter(pk=delegation_id).update(
                    status=FeatureDelegation.STATUS_FAILED,
                    last_error=str(exc),
                )
                delegation = FeatureDelegation.objects.filter(pk=delegation_id).first()
                if delegation:
                    CodingSession.objects.filter(pk=delegation.session_id).update(
                        status=CodingSession.STATUS_FAILED,
                        last_error=str(exc),
                    )
                    cls._notify(delegation, "failed", f"The feature delegation needs attention: {exc}")
        finally:
            with cls._lock:
                cls._active.discard(delegation_id)
            close_old_connections()

    @classmethod
    def resume(
        cls,
        delegation: FeatureDelegation,
        decision: str = "",
        *,
        mode: str = "auto",
    ) -> FeatureDelegation:
        if delegation.status not in [
            FeatureDelegation.STATUS_NEEDS_INPUT,
            FeatureDelegation.STATUS_FAILED,
            FeatureDelegation.STATUS_STOPPED,
        ]:
            raise ValueError("This feature delegation is not waiting to be resumed")
        decision = (decision or "").strip()
        mode = str(mode or "auto").strip().lower()
        if mode not in {"auto", "qa", "coding"}:
            raise ValueError("Resume mode must be auto, qa, or coding")
        if "stop" in decision.casefold():
            cls.stop(delegation)
            delegation.refresh_from_db()
            return delegation
        latest_qa = delegation.qa_runs.order_by("-started_at").first()
        qa_can_retry = bool(
            delegation.qa_enabled
            and latest_qa
            and latest_qa.status in [FeatureQaRun.STATUS_BLOCKED, FeatureQaRun.STATUS_ERROR]
        )
        qa_only = mode == "qa" or (mode == "auto" and qa_can_retry)
        if mode == "qa" and not qa_can_retry:
            raise ValueError("The latest QA run is not blocked or errored, so it cannot be retried directly")
        if not qa_only and delegation.current_iteration >= delegation.max_iterations:
            delegation.max_iterations = min(delegation.max_iterations + 3, 15)
        delegation.status = FeatureDelegation.STATUS_QA if qa_only else FeatureDelegation.STATUS_QUEUED
        delegation.pending_question = ""
        delegation.pending_options = []
        delegation.last_error = ""
        delegation.stopped_at = None
        delegation.save(
            update_fields=[
                "max_iterations", "status", "pending_question", "pending_options",
                "last_error", "stopped_at", "updated_at",
            ]
        )
        CodingSession.objects.filter(pk=delegation.session_id).update(
            status=CodingSession.STATUS_RUNNING,
            pending_question="",
            pending_options=[],
            last_error="",
            stopped_at=None,
        )
        cls._spawn(delegation, continuation=decision, qa_only=qa_only)
        return delegation

    @classmethod
    def stop(cls, delegation: FeatureDelegation) -> FeatureDelegation:
        if delegation.status in [FeatureDelegation.STATUS_COMPLETED, FeatureDelegation.STATUS_STOPPED]:
            return delegation
        delegation.status = FeatureDelegation.STATUS_STOPPED
        delegation.stopped_at = timezone.now()
        delegation.save(update_fields=["status", "stopped_at", "updated_at"])
        for turn_id in delegation.coding_turn_ids:
            turn = CodingTurn.objects.filter(pk=turn_id, status__in=[CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING]).first()
            if turn:
                CodingSessionService.cancel_turn(turn)
        running_qa = delegation.qa_runs.filter(status=FeatureQaRun.STATUS_RUNNING).first()
        if running_qa:
            with cls._lock:
                process = cls._qa_processes.get(str(running_qa.pk))
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            running_qa.status = FeatureQaRun.STATUS_ERROR
            running_qa.error = "Feature delegation was stopped"
            running_qa.completed_at = timezone.now()
            running_qa.save(update_fields=["status", "error", "completed_at"])
        CodingSession.objects.filter(pk=delegation.session_id).update(status=CodingSession.STATUS_READY)
        cls._notify(delegation, "stopped", "The feature delegation was stopped.")
        return delegation

    @classmethod
    def reconcile(cls, delegation: FeatureDelegation):
        if delegation.status in ACTIVE_DELEGATION_STATUSES:
            with cls._lock:
                active = str(delegation.pk) in cls._active
                if active:
                    return
                interrupted_at = timezone.now()
                interrupted_status = delegation.status
                CodingTurn.objects.filter(
                    pk__in=delegation.coding_turn_ids,
                    status__in=[CodingTurn.STATUS_QUEUED, CodingTurn.STATUS_RUNNING],
                ).update(
                    status=CodingTurn.STATUS_CANCELLED,
                    error="Coding turn interrupted by a Corv process restart",
                    completed_at=interrupted_at,
                )
                delegation.qa_runs.filter(status=FeatureQaRun.STATUS_RUNNING).update(
                    status=FeatureQaRun.STATUS_ERROR,
                    error="QA turn interrupted by a Corv process restart",
                    completed_at=interrupted_at,
                )
                qa_only = interrupted_status == FeatureDelegation.STATUS_QA
                # The loop increments before starting a coding turn. Roll that
                # increment back so a restart retries the same implementation cycle.
                if interrupted_status in [
                    FeatureDelegation.STATUS_CODING,
                    FeatureDelegation.STATUS_FIXING,
                ]:
                    delegation.current_iteration = max(0, delegation.current_iteration - 1)
                delegation.status = (
                    FeatureDelegation.STATUS_QA if qa_only else FeatureDelegation.STATUS_QUEUED
                )
                delegation.pending_question = ""
                delegation.pending_options = []
                delegation.last_error = ""
                delegation.save(
                    update_fields=[
                        "current_iteration", "status", "pending_question", "pending_options",
                        "last_error", "updated_at",
                    ]
                )
                CodingSession.objects.filter(pk=delegation.session_id).update(
                    status=CodingSession.STATUS_RUNNING,
                    pending_question="",
                    pending_options=[],
                    last_error="",
                )
                cls._spawn(delegation, qa_only=qa_only)

    @classmethod
    def payload(cls, delegation: FeatureDelegation, include_history: bool = True) -> dict:
        latest_qa = delegation.qa_runs.order_by("-started_at").first()
        qa_runs = delegation.qa_runs.all()[:20] if include_history else []
        turn_ids = delegation.coding_turn_ids[-20:] if include_history else []
        turns_by_id = {
            str(turn.pk): turn
            for turn in CodingTurn.objects.filter(pk__in=turn_ids)
        }
        coding_turns = [
            CodingSessionService.turn_payload(turns_by_id[turn_id])
            for turn_id in reversed(turn_ids)
            if turn_id in turns_by_id
        ]
        return {
            "id": str(delegation.pk),
            "session_id": str(delegation.session_id),
            "session_name": delegation.session.name,
            "machine_name": delegation.session.machine.name,
            "title": delegation.title,
            "description": delegation.description,
            "acceptance_criteria": delegation.acceptance_criteria,
            "qa_enabled": delegation.qa_enabled,
            "max_iterations": delegation.max_iterations,
            "current_iteration": delegation.current_iteration,
            "status": delegation.status,
            "implementation_summary": delegation.implementation_summary,
            "qa_summary": delegation.qa_summary,
            "pending_question": delegation.pending_question,
            "pending_options": delegation.pending_options,
            "last_error": delegation.last_error,
            "artifact_upload_url": f"{str(getattr(settings, 'CORV_PUBLIC_BASE_URL', '') or '').rstrip('/')}/api/files/delegations/{delegation.pk}/upload",
            "can_retry_qa": bool(
                delegation.status in [
                    FeatureDelegation.STATUS_NEEDS_INPUT,
                    FeatureDelegation.STATUS_STOPPED,
                ]
                and delegation.qa_enabled
                and latest_qa
                and latest_qa.status in [FeatureQaRun.STATUS_BLOCKED, FeatureQaRun.STATUS_ERROR]
            ),
            "created_at": delegation.created_at.isoformat(),
            "updated_at": delegation.updated_at.isoformat(),
            "completed_at": delegation.completed_at.isoformat() if delegation.completed_at else None,
            "stopped_at": delegation.stopped_at.isoformat() if delegation.stopped_at else None,
            "coding_turns": coding_turns,
            "qa_runs": [
                {
                    "id": str(run.pk),
                    "iteration": run.iteration,
                    "status": run.status,
                    "summary": run.summary,
                    "failures": run.failures,
                    "evidence": run.evidence,
                    "question": run.question,
                    "options": run.options,
                    "error": run.error,
                    "started_at": run.started_at.isoformat(),
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                }
                for run in qa_runs
            ],
        }
