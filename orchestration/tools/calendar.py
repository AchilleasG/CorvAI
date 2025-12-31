import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

from Corv.config import settings
from orchestration.registry import register_function

# OAuth scope allows read/write access; requires a service account or delegated user.
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
DEFAULT_CALENDAR_ID = settings.google_calendar_default_id or "primary"
DEFAULT_TIMEZONE = settings.google_calendar_default_timezone or "UTC"


def _load_credentials() -> Credentials:
    """
    Load Google credentials from env.

    Supports either:
    - GOOGLE_CALENDAR_CREDENTIALS_JSON: raw service account JSON (string)
    - GOOGLE_CALENDAR_CREDENTIALS_FILE: path to service account JSON file
    Optional: GOOGLE_CALENDAR_DELEGATED_USER to impersonate a user.
    """
    json_blob = settings.google_calendar_credentials_json
    json_path = settings.google_calendar_credentials_file
    delegated_user = settings.google_calendar_delegated_user

    if not json_blob and not json_path:
        raise RuntimeError("Set GOOGLE_CALENDAR_CREDENTIALS_JSON or GOOGLE_CALENDAR_CREDENTIALS_FILE")

    if json_blob:
        info = json.loads(json_blob)
        creds = Credentials.from_service_account_info(info, scopes=CALENDAR_SCOPES)
    else:
        creds = Credentials.from_service_account_file(json_path, scopes=CALENDAR_SCOPES)

    if delegated_user:
        creds = creds.with_subject(delegated_user)
    return creds


def _calendar_service():
    creds = _load_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _delete_event_with_optional_cancel(
    service,
    calendar_id: str,
    event_id: str,
    send_updates: str = "all",
):
    try:
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
            sendUpdates=send_updates,
        ).execute()
    except HttpError as exc:
        raise RuntimeError(f"Google Calendar API error deleting event: {exc}") from exc


@register_function(
    manifest_id="calendar.list_events",
    module="calendar",
    name="calendar.list_events",
    description="List upcoming Google Calendar events.",
    params_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar id (default primary)", "default": "primary"},
            "time_min": {"type": "string", "description": "ISO datetime lower bound; defaults to now (UTC)"},
            "time_max": {"type": "string", "description": "ISO datetime upper bound"},
            "max_results": {"type": "integer", "description": "Max events to return (1-2500)", "default": 25},
            "query": {"type": "string", "description": "Free-text search filter"},
        },
    },
    return_schema={
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "status": {"type": "string"},
                        "summary": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "htmlLink": {"type": "string"},
                        "location": {"type": "string"},
                    },
                },
            }
        },
    },
)
def list_events(
    calendar_id: str = DEFAULT_CALENDAR_ID,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 25,
    query: Optional[str] = None,
):
    service = _calendar_service()

    if max_results < 1 or max_results > 2500:
        raise ValueError("max_results must be between 1 and 2500")

    params: Dict[str, object] = {
        "calendarId": calendar_id,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
        "timeMin": time_min or _now_iso(),
    }
    if time_max:
        params["timeMax"] = time_max
    if query:
        params["q"] = query

    try:
        resp = service.events().list(**params).execute()
        items = resp.get("items", [])
    except HttpError as exc:
        raise RuntimeError(f"Google Calendar API error: {exc}") from exc

    events: List[Dict[str, object]] = []
    for item in items:
        events.append(
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "summary": item.get("summary"),
                "start": (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date"),
                "end": (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date"),
                "htmlLink": item.get("htmlLink"),
                "location": item.get("location"),
            }
        )

    return {"events": events}


@register_function(
    manifest_id="calendar.create_event",
    module="calendar",
    name="calendar.create_event",
    description="Create a Google Calendar event.",
    params_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar id", "default": "primary"},
            "summary": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start datetime ISO 8601"},
            "end": {"type": "string", "description": "End datetime ISO 8601"},
            "timezone": {"type": "string", "description": "IANA timezone for start/end", "default": "UTC"},
            "description": {"type": "string", "description": "Event description"},
            "location": {"type": "string", "description": "Event location"},
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Email addresses to invite",
            },
        },
        "required": ["summary", "start", "end"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "htmlLink": {"type": "string"},
            "status": {"type": "string"},
        },
    },
)
def create_event(
    summary: str,
    start: str,
    end: str,
    calendar_id: str = DEFAULT_CALENDAR_ID,
    timezone: str = DEFAULT_TIMEZONE,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
):
    service = _calendar_service()

    body: Dict[str, object] = {
        "summary": summary,
        "start": {"dateTime": start, "timeZone": timezone},
        "end": {"dateTime": end, "timeZone": timezone},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": email} for email in attendees if email]

    try:
        created = service.events().insert(calendarId=calendar_id, body=body, sendUpdates="all").execute()
    except HttpError as exc:
        raise RuntimeError(f"Google Calendar API error: {exc}") from exc

    return {
        "id": created.get("id"),
        "htmlLink": created.get("htmlLink"),
        "status": created.get("status"),
    }


@register_function(
    manifest_id="calendar.update_event",
    module="calendar",
    name="calendar.update_event",
    description="Update fields on an existing Google Calendar event.",
    params_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar id", "default": "primary"},
            "event_id": {"type": "string", "description": "Event id"},
            "summary": {"type": "string", "description": "New title"},
            "description": {"type": "string", "description": "New description"},
            "start": {"type": "string", "description": "Updated start datetime ISO 8601"},
            "end": {"type": "string", "description": "Updated end datetime ISO 8601"},
            "timezone": {"type": "string", "description": "IANA timezone for start/end"},
            "location": {"type": "string", "description": "Updated location"},
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Replace attendee list with these emails",
            },
            "append_attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Append these attendees instead of replacing",
            },
        },
        "required": ["event_id"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "htmlLink": {"type": "string"},
            "status": {"type": "string"},
            "updated": {"type": "string"},
        },
    },
)
def update_event(
    event_id: str,
    calendar_id: str = DEFAULT_CALENDAR_ID,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    timezone: Optional[str] = DEFAULT_TIMEZONE,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    append_attendees: Optional[List[str]] = None,
):
    service = _calendar_service()

    # Fetch existing event to merge changes.
    try:
        current = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    except HttpError as exc:
        raise RuntimeError(f"Google Calendar API error fetching event: {exc}") from exc

    body: Dict[str, object] = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location

    if start or end or timezone:
        tz = timezone or (current.get("start") or {}).get("timeZone") or "UTC"
        if start:
            body.setdefault("start", {})["dateTime"] = start
        if end:
            body.setdefault("end", {})["dateTime"] = end
        if "start" in body:
            body["start"].setdefault("timeZone", tz)  # type: ignore[index]
        if "end" in body:
            body["end"].setdefault("timeZone", tz)  # type: ignore[index]

    if attendees is not None:
        body["attendees"] = [{"email": email} for email in attendees if email]
    elif append_attendees:
        existing_attendees = current.get("attendees") or []
        existing_emails = {item.get("email") for item in existing_attendees if item.get("email")}
        combined = list(existing_attendees)
        for email in append_attendees:
            if email and email not in existing_emails:
                combined.append({"email": email})
        body["attendees"] = combined

    if not body:
        raise ValueError("No fields provided to update")

    try:
        updated = (
            service.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=body, sendUpdates="all")
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(f"Google Calendar API error updating event: {exc}") from exc

    return {
        "id": updated.get("id"),
        "htmlLink": updated.get("htmlLink"),
        "status": updated.get("status"),
        "updated": updated.get("updated"),
    }


@register_function(
    manifest_id="calendar.delete_event",
    module="calendar",
    name="calendar.delete_event",
    description="Delete a Google Calendar event.",
    params_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar id", "default": DEFAULT_CALENDAR_ID},
            "event_id": {"type": "string", "description": "Event id"},
            "notify_attendees": {
                "type": "boolean",
                "description": "Whether to notify attendees of the cancellation",
                "default": True,
            },
        },
        "required": ["event_id"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "event_id": {"type": "string"},
        },
    },
)
def delete_event(
    event_id: str,
    calendar_id: str = DEFAULT_CALENDAR_ID,
    notify_attendees: bool = True,
):
    service = _calendar_service()
    send_updates = "all" if notify_attendees else "none"
    _delete_event_with_optional_cancel(service, calendar_id, event_id, send_updates)
    return {"status": "deleted", "event_id": event_id}
