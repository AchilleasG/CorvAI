from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Tuple

from django.utils import timezone

from orchestration.model_providers import get_client, resolve_provider
from orchestration.models import OrchestrationSetting
from orchestration.services import ModelConfigService, UserInfoService


ACTIVE_SLOT_STATUSES = {"planned", "deferred", "promoted"}
PREFERRED_MAX_STUDY_SLOTS_PER_DAY = 1


def _safe_json_load(text: str) -> Dict[str, Any]:
	try:
		obj = json.loads(text)
		if isinstance(obj, dict):
			return obj
	except Exception:
		pass
	return {}


def _parse_iso_datetime(value: Any) -> datetime | None:
	if isinstance(value, datetime):
		dt = value
	elif isinstance(value, str):
		try:
			if len(value) == 10 and value[4] == "-" and value[7] == "-":
				return datetime.combine(date.fromisoformat(value), time.min, tzinfo=dt_timezone.utc)
			dt = datetime.fromisoformat(value)
		except Exception:
			return None
	else:
		return None
	if timezone.is_naive(dt):
		dt = dt.replace(tzinfo=dt_timezone.utc)
	return dt.astimezone(dt_timezone.utc)


def _event_bounds(event: Dict[str, Any]) -> Tuple[datetime | None, datetime | None]:
	start_raw = event.get("start")
	end_raw = event.get("end")
	start = _parse_iso_datetime(start_raw)
	end = _parse_iso_datetime(end_raw)
	if isinstance(start_raw, str) and len(start_raw) == 10:
		start = datetime.combine(date.fromisoformat(start_raw), time.min, tzinfo=dt_timezone.utc)
	if isinstance(end_raw, str) and len(end_raw) == 10:
		# Google all-day events use an exclusive end date, so this represents the
		# first instant after the blocked day(s).
		end = datetime.combine(date.fromisoformat(end_raw), time.min, tzinfo=dt_timezone.utc)
	return start, end


def _intervals_overlap(
	a_start: datetime,
	a_end: datetime,
	b_start: datetime,
	b_end: datetime,
) -> bool:
	return a_start < b_end and a_end > b_start


def _slot_bounds(slot: Dict[str, Any]) -> Tuple[datetime | None, datetime | None]:
	return _parse_iso_datetime(slot.get("start_at")), _parse_iso_datetime(slot.get("end_at"))


def _is_nonblocking_reminder(event: Dict[str, Any]) -> bool:
	description = event.get("description")
	if not isinstance(description, str):
		return False
	return "reminder" in description.lower()


def _filter_conflicting_actions(
	actions: List[dict],
	hard_events: List[Dict[str, Any]],
	soft_state: Dict[str, Any],
) -> List[dict]:
	hard_intervals: List[Tuple[datetime, datetime]] = []
	for event in hard_events:
		if not isinstance(event, dict):
			continue
		if _is_nonblocking_reminder(event):
			continue
		if event.get("all_day"):
			continue
		start, end = _event_bounds(event)
		if start and end and end > start:
			hard_intervals.append((start, end))

	slot_index: Dict[str, Dict[str, Any]] = {}
	soft_slot_intervals: List[Tuple[datetime, datetime, str]] = []
	for slot in soft_state.get("slots", []):
		if not isinstance(slot, dict):
			continue
		if slot.get("status") not in ACTIVE_SLOT_STATUSES:
			continue
		slot_id = str(slot.get("id") or "")
		if slot_id:
			slot_index[slot_id] = slot
		start, end = _slot_bounds(slot)
		if start and end and end > start:
			soft_slot_intervals.append((start, end, slot_id))

	filtered: List[dict] = []
	for action in actions:
		if not isinstance(action, dict):
			continue
		action_type = action.get("type")
		if action_type not in {"create_slot", "update_slot", "promote_slot"}:
			filtered.append(action)
			continue

		start = _parse_iso_datetime(action.get("start_at"))
		end = _parse_iso_datetime(action.get("end_at"))
		slot_id = str(action.get("slot_id") or "")
		existing_slot = slot_index.get(slot_id) if slot_id else None

		if action_type in {"update_slot", "promote_slot"} and existing_slot:
			if start is None:
				start = _parse_iso_datetime(existing_slot.get("start_at"))
			if end is None:
				end = _parse_iso_datetime(existing_slot.get("end_at"))

		if not start or not end or end <= start:
			if action_type in {"update_slot", "promote_slot"} and not action.get("start_at") and not action.get("end_at"):
				filtered.append(action)
			continue

		conflicts = any(_intervals_overlap(start, end, hs, he) for hs, he in hard_intervals)
		if not conflicts:
			for ss, se, sid in soft_slot_intervals:
				if action_type in {"update_slot", "promote_slot"} and sid == slot_id:
					continue
				if _intervals_overlap(start, end, ss, se):
					conflicts = True
					break

		if conflicts:
			continue

		filtered.append(action)

	return filtered


def _collect_occupied_intervals(
	hard_events: List[Dict[str, Any]],
	soft_state: Dict[str, Any],
	actions: List[dict],
) -> List[Tuple[datetime, datetime]]:
	occupied: List[Tuple[datetime, datetime]] = []
	slot_index: Dict[str, Dict[str, Any]] = {}

	for event in hard_events:
		if not isinstance(event, dict):
			continue
		if _is_nonblocking_reminder(event) or event.get("all_day"):
			continue
		start, end = _event_bounds(event)
		if start and end and end > start:
			occupied.append((start, end))

	for slot in soft_state.get("slots", []):
		if not isinstance(slot, dict):
			continue
		if slot.get("status") not in ACTIVE_SLOT_STATUSES:
			continue
		slot_id = str(slot.get("id") or "")
		if slot_id:
			slot_index[slot_id] = slot
		start, end = _slot_bounds(slot)
		if start and end and end > start:
			occupied.append((start, end))

	for action in actions:
		if not isinstance(action, dict):
			continue
		atype = action.get("type")
		if atype not in {"create_slot", "update_slot", "promote_slot"}:
			continue
		start = _parse_iso_datetime(action.get("start_at"))
		end = _parse_iso_datetime(action.get("end_at"))
		if atype in {"update_slot", "promote_slot"}:
			slot_id = str(action.get("slot_id") or "")
			slot = slot_index.get(slot_id)
			if slot:
				if not start:
					start = _parse_iso_datetime(slot.get("start_at"))
				if not end:
					end = _parse_iso_datetime(slot.get("end_at"))
		if start and end and end > start:
			occupied.append((start, end))

	occupied.sort(key=lambda x: x[0])
	return occupied


def _is_event_already_slotted(
	event_id: str,
	soft_state: Dict[str, Any],
	actions: List[dict],
) -> bool:
	slot_index: Dict[str, Dict[str, Any]] = {
		str(slot.get("id") or ""): slot
		for slot in soft_state.get("slots", [])
		if isinstance(slot, dict)
	}

	for slot in soft_state.get("slots", []):
		if not isinstance(slot, dict):
			continue
		if slot.get("status") not in ACTIVE_SLOT_STATUSES:
			continue
		if str(slot.get("soft_event_id") or "") == event_id:
			return True

	for action in actions:
		if not isinstance(action, dict):
			continue
		atype = action.get("type")
		if atype == "create_slot" and str(action.get("soft_event_id") or "") == event_id:
			return True
		if atype in {"update_slot", "promote_slot"}:
			slot = slot_index.get(str(action.get("slot_id") or ""))
			if slot and str(slot.get("soft_event_id") or "") == event_id:
				return True

	return False


def _find_first_free_interval(
	*,
	search_start: datetime,
	search_end: datetime,
	duration_minutes: int,
	occupied: List[Tuple[datetime, datetime]],
) -> Tuple[datetime, datetime] | None:
	if duration_minutes <= 0 or search_end <= search_start:
		return None

	duration = timedelta(minutes=duration_minutes)
	cursor = search_start
	step = timedelta(minutes=30)
	while cursor + duration <= search_end:
		conflicts = False
		for busy_start, busy_end in occupied:
			if _intervals_overlap(cursor, cursor + duration, busy_start, busy_end):
				conflicts = True
				break
		if not conflicts:
			return cursor, cursor + duration
		cursor += step

	return None


def _find_first_free_interval_in_day(
	*,
	day: date,
	window_start: datetime,
	window_end: datetime,
	deadline: datetime,
	duration_minutes: int,
	occupied: List[Tuple[datetime, datetime]],
) -> Tuple[datetime, datetime] | None:
	day_start = datetime.combine(day, time(hour=8, minute=0), tzinfo=dt_timezone.utc)
	day_end = datetime.combine(day, time(hour=23, minute=59), tzinfo=dt_timezone.utc)
	search_start = max(window_start, day_start)
	search_end = min(window_end, deadline, day_end)
	if search_end <= search_start:
		return None
	return _find_first_free_interval(
		search_start=search_start,
		search_end=search_end,
		duration_minutes=duration_minutes,
		occupied=occupied,
	)


def _spread_study_create_actions(
	*,
	actions: List[dict],
	hard_events: List[Dict[str, Any]],
	soft_state: Dict[str, Any],
	window_start: datetime,
	window_end: datetime,
) -> List[dict]:
	"""
	Prefer spreading study sessions across distinct days when feasible.
	This only adjusts create_slot actions and never violates conflict constraints.
	"""
	if timezone.is_naive(window_start):
		window_start = window_start.replace(tzinfo=dt_timezone.utc)
	else:
		window_start = window_start.astimezone(dt_timezone.utc)
	if timezone.is_naive(window_end):
		window_end = window_end.replace(tzinfo=dt_timezone.utc)
	else:
		window_end = window_end.astimezone(dt_timezone.utc)

	event_index: Dict[str, Dict[str, Any]] = {
		str(event.get("id") or ""): event
		for event in soft_state.get("soft_events", [])
		if isinstance(event, dict)
	}

	def _is_study_event(event_id: str) -> bool:
		event = event_index.get(event_id)
		if not event:
			return False
		title = str(event.get("title") or "").lower()
		return "study" in title

	day_counts: Dict[date, int] = {}
	for slot in soft_state.get("slots", []):
		if not isinstance(slot, dict) or slot.get("status") not in ACTIVE_SLOT_STATUSES:
			continue
		event_id = str(slot.get("soft_event_id") or "")
		if not _is_study_event(event_id):
			continue
		start = _parse_iso_datetime(slot.get("start_at"))
		if not start:
			continue
		day = start.date()
		day_counts[day] = int(day_counts.get(day, 0)) + 1

	occupied = _collect_occupied_intervals(hard_events, soft_state, [])
	rebalanced: List[dict] = []

	for action in actions:
		if not isinstance(action, dict) or action.get("type") != "create_slot":
			rebalanced.append(action)
			continue

		event_id = str(action.get("soft_event_id") or "")
		start = _parse_iso_datetime(action.get("start_at"))
		end = _parse_iso_datetime(action.get("end_at"))
		if not event_id or not start or not end or end <= start:
			rebalanced.append(action)
			continue

		duration_minutes = int((end - start).total_seconds() // 60)
		event = event_index.get(event_id) or {}
		hard_deadline = _parse_iso_datetime(event.get("hard_deadline"))
		soft_deadline = _parse_iso_datetime(event.get("soft_deadline"))
		deadline = hard_deadline or soft_deadline or window_end
		deadline = min(deadline, window_end)

		final_start = start
		final_end = end
		if _is_study_event(event_id):
			original_day = start.date()
			orig_count = int(day_counts.get(original_day, 0))
			if orig_count >= PREFERRED_MAX_STUDY_SLOTS_PER_DAY:
				candidate_days = []
				day_cursor = max(window_start.date(), start.date())
				last_day = deadline.date()
				while day_cursor <= last_day:
					candidate_days.append(day_cursor)
					day_cursor += timedelta(days=1)
				candidate_days.sort(key=lambda d: (int(day_counts.get(d, 0)), d))

				for day in candidate_days:
					if day == original_day:
						continue
					if int(day_counts.get(day, 0)) > int(day_counts.get(original_day, 0)):
						continue
					placement = _find_first_free_interval_in_day(
						day=day,
						window_start=window_start,
						window_end=window_end,
						deadline=deadline,
						duration_minutes=duration_minutes,
						occupied=occupied,
					)
					if placement:
						final_start, final_end = placement
						break

		occupied.append((final_start, final_end))
		if _is_study_event(event_id):
			day_counts[final_start.date()] = int(day_counts.get(final_start.date(), 0)) + 1

		if final_start != start or final_end != end:
			updated = dict(action)
			updated["start_at"] = final_start.isoformat()
			updated["end_at"] = final_end.isoformat()
			rebalanced.append(updated)
		else:
			rebalanced.append(action)

	return rebalanced


def plan_soft_window(
	*,
	hard_events: List[Dict[str, Any]],
	soft_state: Dict[str, Any],
	window_start,
	window_end,
	planner_note: str | None = None,
	model: str | None = None,
) -> Tuple[List[dict], str]:
	"""
	Ask the model to propose actions for soft events given hard events and current slots.
	Returns (actions, planner_trace_id).
	"""
	model_name = model or ModelConfigService.get_soft_planner_model()
	provider = resolve_provider(model_name)
	planner_trace_id = str(uuid.uuid4())
	planner_note_block = f"Planner note (hard constraint): {planner_note}\n" if planner_note else ""

	instructions = (
		"You are the Soft Event Planner. Given hard calendar events and flexible soft events, propose scheduling changes within the window.\n"
		"Hard events are fixed. Soft events have preferred/min duration bounds, deadlines, deferral limits, and may include notes/description. Existing soft slots may already be planned.\n"
		"You may also receive objective_inputs describing the underlying objectives, tasks, recent logs, and prior slot outcomes that produced some of the soft events. Use that information heavily when deciding what to re-include and where.\n"
		"Use each hard event's summary, description, location, and exact start/end times as authoritative scheduling context. If a hard event description or title suggests work, a day job, a meeting, a class, an appointment, travel, or another fixed commitment, treat the occupied time as blocked unless the event is explicitly a non-blocking reminder.\n"
		"All-day events are context only and must not be treated as blocked space.\n"
		"If a hard event description contains the word reminder anywhere, treat it as non-blocking and ignore it for scheduling.\n"
		"If a user scheduling constraint is provided, treat it as a hard requirement.\n"
		"User notes are hard constraints, not soft suggestions.\n"
		f"{planner_note_block}"
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
		"- Hard calendar events may include all_day, duration_minutes, and spans_multiple_days. Treat all_day events as context-only (non-blocking) and honor timed events as blocking constraints.\n"
		"- If a hard event looks like a reminder, habit, or background note (for example medication, vitamins, take pill, reminder, journal, or similar) and it has no meaningful time block, do not treat it as blocking calendar time unless the event clearly occupies time.\n"
		"- Leave reasonable transition buffers before and after activities whenever practical; avoid placing soft-event slots immediately adjacent to other commitments by default.\n"
		"- For each soft event, planned slot duration must be between min_duration_minutes and preferred_duration_minutes (inclusive).\n"
		"- Prefer slots close to preferred_duration_minutes, but use shorter valid durations when needed.\n"
		"- Respect deferral limits and deadlines; prioritize sooner deadlines and higher priority.\n"
		"- When there are multiple valid placement days before a deadline, spread study sessions across as many distinct days as practical instead of clustering several into one day. Prefer around one study session per day unless deadline pressure makes clustering necessary.\n"
		"- Treat completed prior sessions as evidence of progress. Treat skipped or missed prior sessions and blocker logs as signals that the original timing may have been poor; avoid repeating obviously bad placements when practical.\n"
		"- Use objective task status, recent logs, and prior slot outcome history to decide whether work should be scheduled earlier, later, in longer blocks, or in shorter/lighter blocks.\n"
		"- For objective-backed work, every task with a due date inside the window must be represented by at least one slot before its deadline. If an objective itself has a deadline inside the window, make sure its urgent tasks are scheduled before that deadline too.\n"
		"- If coverage is tight, compress durations toward the minimum and use denser placement when necessary. Rare late-night placement is allowed only when deadline pressure genuinely requires it.\n"
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
		"planner_note": planner_note,
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

	actions = _filter_conflicting_actions(actions, hard_events, soft_state)
	actions = _spread_study_create_actions(
		actions=actions,
		hard_events=hard_events,
		soft_state=soft_state,
		window_start=window_start,
		window_end=window_end,
	)

	return actions, planner_trace_id


__all__ = ["plan_soft_window"]
