from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Tuple

from django.utils import timezone

from orchestration.model_providers import resolve_provider, get_client
from orchestration.services import ModelConfigService
from orchestration.models import OrchestrationSetting


def _safe_json_load(text: str) -> Dict[str, Any]:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {}


def plan_soft_window(
    *,
    hard_events: List[Dict[str, Any]],
    soft_state: Dict[str, Any],
    window_start,
    window_end,
    model: str | None = None,
) -> Tuple[List[dict], str]:
    """
    Ask the caller model to propose actions for soft events given hard events and current slots.
    Returns (actions, planner_trace_id).
    """
    model_name = model or ModelConfigService.get_caller_model()
    provider = resolve_provider(model_name)
    planner_trace_id = str(uuid.uuid4())

    instructions = (
        "You are the Soft Event Planner. Given hard calendar events and flexible soft events, propose scheduling changes within the window.\n"
        "Hard events are fixed. Soft events have duration, deadlines, deferral limits, and may include notes. Existing soft slots may already be planned.\n"
        "Return JSON with 'actions' (array) and an optional 'summary'.\n" \
        "If a soft event is reaching its deadline and you deem the user might not get another good chance to do it later, promote it to a hard event.\n" \
        "If no changes are needed, return an empty 'actions' array.\n" \
        "When planning events please consider the timing of each task, how long it will take, and any deadlines or priorities associated with it, as well as what energy levels are required and how those usually fluctuate throughout the day.\n" \
        "Also consider possible time for commune if the task is implied to benefit from it.\n As well as any other context you have about the user and their typical schedule and habits.\n Or any other buffers that might be needed.\n"
        "Actions allowed:\n"
        "- create_slot: {type, soft_event_id, start_at, end_at, notify_at?, rationale?, metadata?}\n"
        "- update_slot: {type, slot_id, start_at?, end_at?, notify_at?, status?, rationale?, metadata?}\n"
        "- cancel_slot: {type, slot_id}\n"
        "- promote_slot: {type, slot_id, start_at?, end_at?, summary?, description?, calendar_id?, timezone?}\n"
        "Rules:\n"
        "- Keep scheduling within the window provided.\n"
        "- Avoid overlapping hard events and existing slots.\n"
        "- Respect deferral limits and deadlines; prioritize sooner deadlines and higher priority.\n"
        "- If a soft event is at risk (few remaining viable slots, deadline near, or max deferrals), propose promote_slot so it lands on the calendar.\n"
        "- Keep output concise; avoid redundant updates."
    )

    now = timezone.now().isoformat()
    window_block = f"Window start: {window_start.isoformat()}, end: {window_end.isoformat()}, now: {now}"
    payload = {
        "hard_events": hard_events,
        "soft_events": soft_state.get("soft_events", []),
        "slots": soft_state.get("slots", []),
    }
    habits = (
        OrchestrationSetting.objects.filter(key="calendar_habits_text")
        .values_list("value", flat=True)
        .first()
        or ""
    )
    habits_block = f"\nScheduling habits:\n{habits}" if habits else ""
    prompt_text = f"{instructions}{habits_block}\n{window_block}\nData:\n{json.dumps(payload, default=str)}"

    actions: List[dict] = []
    if provider == "openai":
        resp = get_client("openai").responses.create(
            model=model_name,
            input=[
                {"role": "developer", "content": [{"type": "input_text", "text": prompt_text}]},
            ],
            tools=[],
            text={"format": {"type": "json_object"}},
            store=False,
        )
        raw = getattr(resp, "output_text", "{}") or "{}"
        data = _safe_json_load(raw)
        actions = data.get("actions") or []
    else:
        resp = get_client("xai").chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": f"{instructions}{habits_block}",
                },
                {"role": "user", "content": f"{window_block}\nData:\n{json.dumps(payload, default=str)}"},
            ],
            response_format={"type": "json_object"},
        )
        raw = "{}"
        if getattr(resp, "choices", None):
            raw = resp.choices[0].message.content or "{}"  # type: ignore[assignment]
        data = _safe_json_load(raw)
        actions = data.get("actions") or []

    return actions, planner_trace_id
