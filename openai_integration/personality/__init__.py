from __future__ import annotations

from typing import List, Optional

from django.db.models import Prefetch

from mcp.models import AssistantPersona, PersonaUserProfile

DEFAULT_PERSONA_SLUG = "corv"
DEFAULT_USER_PROFILE_ID = "default"


def _fetch_persona(slug: Optional[str] = None) -> Optional[AssistantPersona]:
    persona_slug = slug or DEFAULT_PERSONA_SLUG
    return (
        AssistantPersona.objects.prefetch_related(
            Prefetch("user_profiles", queryset=PersonaUserProfile.objects.order_by("-is_default", "profile_id"))
        )
        .filter(slug=persona_slug)
        .first()
    )


def build_personality_system_message(persona_slug: Optional[str] = None) -> str:
    """
    Compose the system prompt that anchors every completion by stitching together
    the database-stored prompt and style guardrails.
    """
    persona = _fetch_persona(persona_slug)
    if not persona:
        return (
            "You are Corv, the resident operations co-pilot for lean engineering teams. "
            "Stay grounded, enumerate risks, and respond with pragmatic next steps."
        )

    prompt = (persona.system_prompt or "").strip()
    guidelines = persona.style_guidelines or []

    if guidelines:
        formatted = "\n".join(f"- {item}" for item in guidelines if item)
        prompt = f"{prompt}\n\nGuidelines:\n{formatted}"

    return prompt


def resolve_user_profile(
    persona_slug: Optional[str] = None, profile_id: Optional[str] = None
) -> Optional[PersonaUserProfile]:
    persona = _fetch_persona(persona_slug)
    if not persona:
        return None

    if profile_id:
        profile = next((p for p in persona.user_profiles.all() if p.profile_id == profile_id), None)
        if profile:
            return profile

    default_profile = next((p for p in persona.user_profiles.all() if p.is_default), None)
    if default_profile:
        return default_profile

    return persona.user_profiles.first()


def build_user_profile_message(
    profile_id: Optional[str] = None, persona_slug: Optional[str] = None
) -> Optional[str]:
    """
    Convert the stored profile metadata into a short descriptor that can be
    injected into the pre-chat context.
    """
    profile = resolve_user_profile(persona_slug=persona_slug, profile_id=profile_id)
    if not profile:
        return None

    parts: List[str] = []
    if profile.name and profile.role:
        parts.append(f"Primary user: {profile.name} ({profile.role}).")
    elif profile.name:
        parts.append(f"Primary user: {profile.name}.")
    elif profile.role:
        parts.append(f"Primary user role: {profile.role}.")

    if profile.summary:
        parts.append(profile.summary)

    def _format_list(label: str, values: List[str]):
        if not values:
            return None
        bullets = "\n".join(f"- {item}" for item in values if item)
        if not bullets:
            return None
        return f"{label}:\n{bullets}"

    goals_section = _format_list("Goals", profile.goals or [])
    if goals_section:
        parts.append(goals_section)

    pref_section = _format_list("Preferences", profile.preferences or [])
    if pref_section:
        parts.append(pref_section)

    message = "\n".join(parts).strip()
    return message or None


__all__ = [
    "build_personality_system_message",
    "build_user_profile_message",
    "resolve_user_profile",
    "DEFAULT_PERSONA_SLUG",
    "DEFAULT_USER_PROFILE_ID",
]
