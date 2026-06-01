from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Tuple

from django.utils import timezone

from orchestration.model_providers import get_client, resolve_provider
from orchestration.models import OrchestrationSetting
from orchestration.services import ModelConfigService, UserInfoService


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
	Ask the model to propose actions for soft events given hard events and current slots.
	Returns (actions, planner_trace_id).
	"""
	model_name = model or ModelConfigService.get_soft_planner_model()
	provider = resolve_provider(model_name)
	planner_trace_id = str(uuid.uuid4())

	instructions = (
		"You are the Soft Event Planner. Given hard calendar events and flexible soft events, propose scheduling changes within the window.\n"
		"Hard events are fixed. Soft events have preferred/min duration bounds, deadlines, deferral limits, and may include notes/description. Existing soft slots may already be planned.\n"
		"You may also receive objective_inputs describing the underlying objectives, tasks, recent logs, and prior slot outcomes that produced some of the soft events. Use that information heavily when deciding what to re-include and where.\n"
		"If a user scheduling constraint is provided, treat it as a hard requirement.\n"
		"Return JSON with 'actions' (array) and an optional 'summary'.\n"
		"Do not promote a soft event to a hard calendar event unless the user explicitly asked for that promotion.\n"
		"If no changes are needed, return an empty 'actions' array.\n"
		"When planning events please consider the timing of each task, how long it will take, and any deadlines or priorities associated with it, as well as what energy levels are required and how those usually fluctuate throughout the day.\n"
		"Strongly prefer leaving reasonable gaps between activities. Do not stack activities directly back-to-back unless the schedule is constrained or the user has clearly indicated a preference for dense scheduling.\n"
		"Assume, within reason, that commute, setup, transition, decompression, or wrap-up time may be needed depending on the nature of the task, unless the user explicitly states otherwise.\n"
		"Also assume reasonable error margins and buffers for tasks whose duration, travel, preparation, or recovery time is uncertain.\n"
		"Use any other context you have about the user and their typical schedule and habits when deciding how much buffer is appropriate.\n"
		"Actions allowed:\n"
		"- create_slot: {type, soft_event_id, start_at, end_at, notify_at?, rationale?, metadata?}\n"
		"- update_slot: {type, slot_id, start_at?, end_at?, notify_at?, status?, rationale?, metadata?}\n"
		"- cancel_slot: {type, slot_id}\n"
		"- promote_slot: {type, slot_id, start_at?, end_at?, summary?, description?, calendar_id?, timezone?}\n"
		"Rules:\n"
		"- Keep scheduling within the window provided.\n"
		"- NEVER place a soft slot so that it overlaps any hard calendar event, even partially. Hard events are absolute, immovable blocks. A soft slot must not start before a hard event ends, and must not end after a hard event starts, if those times intersect. This is the single most important constraint - violating it is never acceptable regardless of deadlines or priorities.\n"
		"- Avoid overlapping existing soft slots.\n"
		"- Hard calendar events may include all_day, duration_minutes, and spans_multiple_days. Treat all_day or spans_multiple_days events as full-day or multi-day blocks, not ordinary short meetings.\n"
		"- If a hard event looks like a reminder, habit, or background note (for example medication, vitamins, take pill, reminder, journal, or similar) and it has no meaningful time block, do not treat it as blocking calendar time unless the event clearly occupies time.\n"
		"- Leave reasonable transition buffers before and after activities whenever practical; avoid placing soft-event slots immediately adjacent to other commitments by default.\n"
		"- For each soft event, planned slot duration must be between min_duration_minutes and preferred_duration_minutes (inclusive).\n"
		"- Prefer slots close to preferred_duration_minutes, but use shorter valid durations when needed.\n"
		"- Respect deferral limits and deadlines; prioritize sooner deadlines and higher priority.\n"
		"- Treat completed prior sessions as evidence of progress. Treat skipped or missed prior sessions and blocker logs as signals that the original timing may have been poor; avoid repeating obviously bad placements when practical.\n"
		"- Use objective task status, recent logs, and prior slot outcome history to decide whether work should be scheduled earlier, later, in longer blocks, or in shorter/lighter blocks.\n"
		"- If a soft event is at risk, prefer better slot placement or leave it unslotted; do not propose promote_slot unless the user explicitly requested promotion.\n"
		"- Keep output concise; avoid redundant updates."
	)

	now = timezone.now().isoformat()
	window_block = f"Window start: {window_start.isoformat()}, end: {window_end.isoformat()}, now: {now}"
	payload = {
		"hard_events": hard_events,
		"soft_events": soft_state.get("soft_events", []),
		"slots": soft_state.get("slots", []),
		"objective_inputs": soft_state.get("objective_inputs", []),
	}
	habits = (
		OrchestrationSetting.objects.filter(key="calendar_habits_text")
		.values_list("value", flat=True)
		.first()
		or ""
	)
	habits_block = f"\nScheduling habits:\n{habits}" if habits else ""
	core_profile_block = UserInfoService.format_core_profile_block()
	core_notes = ""
	if core_profile_block:
		core_notes = f"\nCore user context:\n{core_profile_block}"
	prompt_text = f"{instructions}{core_notes}{habits_block}\n{window_block}\nData:\n{json.dumps(payload, default=str)}"

	actions: List[dict] = []
	if provider == "openai":
		resp = get_client("openai").responses.create(
			model=model_name,
			input=[
				{
					"role": "developer",
					"content": [{"type": "input_text", "text": prompt_text}],
				},
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
					"content": f"{instructions}{core_notes}{habits_block}",
				},
				{
					"role": "user",
					"content": f"{window_block}\nData:\n{json.dumps(payload, default=str)}",
				},
			],
			response_format={"type": "json_object"},
		)
		raw = "{}"
		if getattr(resp, "choices", None):
			raw = resp.choices[0].message.content or "{}"  # type: ignore[assignment]
		data = _safe_json_load(raw)
		actions = data.get("actions") or []

	return actions, planner_trace_id


__all__ = ["plan_soft_window"]
