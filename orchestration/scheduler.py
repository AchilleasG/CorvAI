from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from django.db import transaction
from django.utils import timezone

from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.schemas import FunctionCallPayload
from orchestration.services import FunctionRunnerService, ModuleDirectory
from orchestration.models import (
    ScheduledTask,
    ScheduledTaskRun,
    ScheduledTaskLogEntry,
)


NO_CLARIFICATION_NOTE = (
    "No user clarifications are available. Do not ask the user; make reasonable "
    "assumptions and complete the task to the best of your ability."
)


def _add_months(dt: datetime, months: int = 1) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def compute_next_run(task: ScheduledTask, *, from_dt: Optional[datetime] = None) -> Optional[datetime]:
    base = from_dt or task.next_run_at or task.start_at
    if not base:
        return None
    if task.recurrence == ScheduledTask.RECURRENCE_ONCE:
        return None
    if task.recurrence == ScheduledTask.RECURRENCE_DAILY:
        return base + timedelta(days=1)
    if task.recurrence == ScheduledTask.RECURRENCE_WEEKLY:
        return base + timedelta(weeks=1)
    if task.recurrence == ScheduledTask.RECURRENCE_MONTHLY:
        return _add_months(base, 1)
    return None


def log_run(run: ScheduledTaskRun, message: str, *, role: str = "system", level: str = "info"):
    ScheduledTaskLogEntry.objects.create(run=run, role=role, level=level, message=message)


def _summarize_results(prior_results: List[Dict[str, Any]], summary: Any) -> str:
    summary_text = summary if isinstance(summary, str) else (str(summary) if summary is not None else "")
    if not prior_results:
        return summary_text or "No actions taken."
    lines = [summary_text or "Completed calls."]
    lines.extend(f"- {r.get('function_id')}: {r.get('status')}" for r in prior_results)
    return "\n".join(lines)


def _plan_with_no_clarifications(
    *,
    user_request: str,
    tool_catalog: List[Dict[str, Any]],
    prior_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    for attempt in range(2):
        decision = FunctionCallOrchestrator._plan_next_action(
            user_request=user_request,
            tool_catalog=tool_catalog,
            prior_results=prior_results,
            job=None,
            chat_id=None,
        )
        if not decision.get("ask_user"):
            return decision
        if attempt == 0:
            user_request = (
                f"{user_request}\n\nSystem: {NO_CLARIFICATION_NOTE} "
                "If details are missing, choose sensible defaults and proceed."
            )
    # If the planner still asks the user, force a no-op completion.
    return {"done": True, "summary": "Planner requested user input; completed with best-effort assumptions."}


def execute_task(task: ScheduledTask, *, max_steps: int = 5) -> ScheduledTaskRun:
    run = ScheduledTaskRun.objects.create(
        task=task,
        status=ScheduledTaskRun.STATUS_RUNNING,
        started_at=timezone.now(),
    )
    log_run(run, f"Scheduled task started. Recurrence: {task.recurrence}")
    tool_catalog = ModuleDirectory.function_catalog()
    prior_results: List[Dict[str, Any]] = []
    user_request = f"Scheduled task:\n{task.prompt}\n\n{NO_CLARIFICATION_NOTE}"

    try:
        for step in range(max_steps):
            decision = _plan_with_no_clarifications(
                user_request=user_request,
                tool_catalog=tool_catalog,
                prior_results=prior_results,
            )

            if decision.get("ask_user"):
                log_run(run, f"Planner asked user: {decision['ask_user']}", role="caller", level="warn")
                break

            call = decision.get("call")
            if call and call.get("function_id"):
                payload = FunctionCallPayload(
                    trace_id="scheduled-task",
                    function_id=call["function_id"],
                    params=call.get("params") or {},
                    job_id=None,
                )
                log_run(run, f"Calling {payload.function_id} with params: {payload.params}", role="caller")
                result = FunctionRunnerService.run_function_call(payload, job=None)
                coerced = FunctionCallOrchestrator._coerce_result_payload(result)
                coerced["function_id"] = call["function_id"]
                coerced["params"] = call.get("params") or {}
                prior_results.append(coerced)
                log_run(
                    run,
                    f"Function result: {FunctionCallOrchestrator._summarize_result_for_log(result, truncated=coerced.get('truncated', False), truncation_reason=coerced.get('truncation_reason', ''))}",
                    role="runner",
                )
                continue

            if decision.get("done"):
                summary = decision.get("summary") or "Completed."
                run.summary = _summarize_results(prior_results, summary)
                break

        if not run.summary:
            run.summary = _summarize_results(prior_results, "Completed.")
        run.status = ScheduledTaskRun.STATUS_COMPLETED
        log_run(run, f"TL;DR: {run.summary}", role="frontman")
    except Exception as exc:  # pragma: no cover
        run.status = ScheduledTaskRun.STATUS_FAILED
        run.error_summary = str(exc)
        log_run(run, f"Run failed: {exc}", level="error")
    finally:
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at", "summary", "error_summary"])

    return run


@transaction.atomic
def claim_due_task(task_id) -> Optional[ScheduledTask]:
    updated = (
        ScheduledTask.objects.filter(id=task_id, status=ScheduledTask.STATUS_ACTIVE, is_running=False)
        .update(is_running=True, updated_at=timezone.now())
    )
    if updated:
        return ScheduledTask.objects.get(id=task_id)
    return None


def poll_due_tasks(limit: int = 25) -> int:
    now = timezone.now()
    due = list(
        ScheduledTask.objects.filter(
            status=ScheduledTask.STATUS_ACTIVE,
            is_running=False,
            next_run_at__isnull=False,
            next_run_at__lte=now,
        ).order_by("next_run_at")[:limit]
    )
    ran = 0
    for task in due:
        claimed = claim_due_task(task.id)
        if not claimed:
            continue
        run = execute_task(claimed)
        claimed.last_run_at = run.finished_at or timezone.now()
        next_run = compute_next_run(claimed, from_dt=claimed.next_run_at or claimed.last_run_at)
        if next_run is None:
            claimed.status = ScheduledTask.STATUS_COMPLETED
        else:
            while next_run <= now:
                next_run = compute_next_run(claimed, from_dt=next_run)
                if next_run is None:
                    break
            claimed.next_run_at = next_run
        claimed.is_running = False
        claimed.save(update_fields=["last_run_at", "next_run_at", "status", "is_running", "updated_at"])
        ran += 1
    return ran
