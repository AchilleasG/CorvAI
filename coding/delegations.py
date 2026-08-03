from __future__ import annotations

import glob
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from django.db import close_old_connections
from django.utils import timezone

from coding.auth import CodexDeviceAuthService
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
    ) -> FeatureDelegation:
        if not CodexDeviceAuthService._is_authenticated():
            raise ValueError("Sign in to Codex before creating a feature delegation")
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
        delegation = FeatureDelegation.objects.create(
            session=session,
            title=title.strip(),
            description=description.strip(),
            acceptance_criteria=criteria,
            qa_enabled=bool(qa_enabled),
            max_iterations=max(1, min(int(max_iterations), 12)),
        )
        cls._spawn(delegation)
        return delegation

    @classmethod
    def _spawn(cls, delegation: FeatureDelegation, continuation: str = ""):
        key = str(delegation.pk)
        with cls._lock:
            if key in cls._active:
                raise ValueError("This feature delegation is already running")
            cls._active.add(key)
        threading.Thread(
            target=cls._run_loop,
            args=(key, continuation),
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
        return f"""Feature delegation: {delegation.title}

Description:
{delegation.description}

Acceptance criteria:
{cls._criteria_text(delegation)}

{context}

Do not stop after analysis. Inspect the existing remote repository, implement the work, run relevant tests, and verify it. Continue autonomously unless a material product decision or external blocker truly requires the user.
"""

    @classmethod
    def _qa_prompt(cls, delegation: FeatureDelegation, qa_run: FeatureQaRun) -> str:
        evidence_dir = CodingSessionService.workspace_dir(delegation.session) / "qa-evidence" / str(qa_run.pk)
        return f"""You are the independent QA bot for this feature. Do not edit application code.

Feature: {delegation.title}
Description: {delegation.description}
Acceptance criteria:
{cls._criteria_text(delegation)}

Coder's latest report:
{delegation.implementation_summary}

Work on the same configured SSH target. Inspect the actual diff and repository state, run focused and regression tests, and independently verify every acceptance criterion. Do not accept the coder's report without evidence.

If this is a web UI or browser behavior, actually start/check the application when practical and use the local browser harness. Write a JSON spec, then run:
  ./qa-browser SPEC.json --output-dir {evidence_dir}
Interact with meaningful controls, assert rendered results, capture screenshots, and inspect browser console errors. The target URL must come from the task/configuration or be safely inferred. For an app bound to localhost on the SSH machine, use the harness's ssh_tunnel spec so the browser can reach it; only report blocked after trying the available tunnel safely.

Return passed only when all acceptance criteria are demonstrated. Return failed with concrete reproducible failures when the coder should fix the work. Return blocked only for an external dependency or user decision that testing cannot resolve.
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
    def _run_qa(cls, delegation: FeatureDelegation) -> FeatureQaRun:
        qa_run = FeatureQaRun.objects.create(
            delegation=delegation,
            iteration=delegation.current_iteration,
        )
        log_lines: list[str] = []
        try:
            result, thread_id, first_log = cls._execute_qa_turn(
                delegation,
                qa_run,
                cls._qa_prompt(delegation, qa_run),
            )
            log_lines.extend(first_log)
            evidence_dir = CodingSessionService.workspace_dir(delegation.session) / "qa-evidence" / str(qa_run.pk)
            screenshots = sorted(
                glob.glob(str(evidence_dir / "**" / "*.png"), recursive=True)
                + glob.glob(str(evidence_dir / "**" / "*.jpg"), recursive=True)
            )[-5:]
            if screenshots:
                visual_prompt = (
                    "Review the attached screenshots as visual QA evidence. Combine them with your "
                    "test results and acceptance criteria, check for visible regressions, clipping, "
                    "overlap, broken states, and incorrect content, then return the final QA verdict."
                )
                result, thread_id, visual_log = cls._execute_qa_turn(
                    delegation,
                    qa_run,
                    visual_prompt,
                    screenshots,
                )
                log_lines.extend(visual_log)
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
        return qa_run

    @classmethod
    def _run_loop(cls, delegation_id: str, continuation: str = ""):
        close_old_connections()
        try:
            while True:
                delegation = FeatureDelegation.objects.select_related("session__machine").get(pk=delegation_id)
                if delegation.status == FeatureDelegation.STATUS_STOPPED:
                    return
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
                qa_run = cls._run_qa(delegation)
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
    def resume(cls, delegation: FeatureDelegation, decision: str = "") -> FeatureDelegation:
        if delegation.status not in [
            FeatureDelegation.STATUS_NEEDS_INPUT,
            FeatureDelegation.STATUS_FAILED,
        ]:
            raise ValueError("This feature delegation is not waiting to be resumed")
        decision = (decision or "").strip()
        if "stop" in decision.casefold():
            cls.stop(delegation)
            delegation.refresh_from_db()
            return delegation
        if delegation.current_iteration >= delegation.max_iterations:
            delegation.max_iterations = min(delegation.max_iterations + 3, 15)
        delegation.status = FeatureDelegation.STATUS_QUEUED
        delegation.pending_question = ""
        delegation.pending_options = []
        delegation.last_error = ""
        delegation.save(
            update_fields=[
                "max_iterations", "status", "pending_question", "pending_options",
                "last_error", "updated_at",
            ]
        )
        cls._spawn(delegation, continuation=decision)
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
        return delegation

    @classmethod
    def reconcile(cls, delegation: FeatureDelegation):
        if delegation.status in ACTIVE_DELEGATION_STATUSES:
            with cls._lock:
                active = str(delegation.pk) in cls._active
            if not active:
                interrupted_at = timezone.now()
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
                delegation.status = FeatureDelegation.STATUS_NEEDS_INPUT
                delegation.pending_question = "The Corv process restarted while this delegation was running. Resume it from the saved Codex threads?"
                delegation.pending_options = ["Resume", "Stop the delegation"]
                delegation.last_error = "Delegation interrupted by a Corv process restart"
                delegation.save(
                    update_fields=[
                        "status", "pending_question", "pending_options", "last_error", "updated_at",
                    ]
                )
                CodingSession.objects.filter(pk=delegation.session_id).update(
                    status=CodingSession.STATUS_NEEDS_INPUT,
                    pending_question="",
                    pending_options=[],
                    last_error=delegation.last_error,
                )

    @classmethod
    def payload(cls, delegation: FeatureDelegation, include_history: bool = True) -> dict:
        cls.reconcile(delegation)
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
