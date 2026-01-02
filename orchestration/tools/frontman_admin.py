from typing import Optional

from django.db import transaction

from orchestration.models import FrontmanPersona
from orchestration.registry import register_function


@register_function(
    manifest_id="frontman_admin.list_personas",
    module="frontman_admin",
    description="List all Frontman personas with active flag.",
    params_schema={"type": "object", "properties": {}},
    return_schema={
        "type": "object",
        "properties": {
            "personas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "name": {"type": "string"},
                        "is_active": {"type": "boolean"},
                        "instructions": {"type": "string"},
                        "postamble": {"type": "string"},
                    },
                },
            }
        },
    },
)
def list_personas():
    out = []
    for p in FrontmanPersona.objects.all().order_by("-updated_at", "-created_at"):
        out.append(
            {
                "slug": p.slug,
                "name": p.name,
                "is_active": p.is_active,
                "instructions": p.instructions,
                "postamble": p.postamble or "",
            }
        )
    return {"personas": out}


@register_function(
    manifest_id="frontman_admin.get_persona",
    module="frontman_admin",
    description="Get the latest Frontman persona (instructions + postamble).",
    params_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Optional persona slug"},
        },
    },
    return_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string"},
            "name": {"type": "string"},
            "instructions": {"type": "string"},
            "postamble": {"type": "string"},
            "is_active": {"type": "boolean"},
        },
    },
)
def get_persona(slug: Optional[str] = None):
    qs = FrontmanPersona.objects.all()
    persona = None
    if slug:
        persona = qs.filter(slug=slug).first()
    else:
        persona = qs.order_by("-created_at").first()
    if not persona:
        return {"slug": None, "name": None, "instructions": "", "postamble": ""}
    return {
        "slug": persona.slug,
        "name": persona.name,
        "instructions": persona.instructions,
        "postamble": persona.postamble or "",
        "is_active": persona.is_active,
    }


@register_function(
    manifest_id="frontman_admin.set_persona",
    module="frontman_admin",
    description="Create or update a Frontman persona (overwrite instructions and postamble).",
    params_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Persona slug (required)"},
            "name": {"type": "string", "description": "Display name (required)"},
            "instructions": {"type": "string", "description": "Main persona instructions"},
            "postamble": {"type": "string", "description": "Additional instructions appended after persona"},
        },
        "required": ["slug", "name", "instructions"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string"},
            "name": {"type": "string"},
            "instructions": {"type": "string"},
            "postamble": {"type": "string"},
            "is_active": {"type": "boolean"},
        },
    },
)
@transaction.atomic
def set_persona(slug: str, name: str, instructions: str, postamble: str = ""):
    persona, _ = FrontmanPersona.objects.update_or_create(
        slug=slug,
        defaults={
            "name": name,
            "instructions": instructions,
            "postamble": postamble,
        },
    )
    return {
        "slug": persona.slug,
        "name": persona.name,
        "instructions": persona.instructions,
        "postamble": persona.postamble or "",
        "is_active": persona.is_active,
    }


@register_function(
    manifest_id="frontman_admin.append_postamble",
    module="frontman_admin",
    description="Append text to the latest persona's postamble (or a specific slug).",
    params_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Optional persona slug"},
            "append_text": {"type": "string", "description": "Text to append"},
            "separator": {
                "type": "string",
                "description": "Separator between existing and new text",
                "default": "\n",
            },
        },
        "required": ["append_text"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string"},
            "name": {"type": "string"},
            "instructions": {"type": "string"},
            "postamble": {"type": "string"},
        },
    },
)
@transaction.atomic
def append_postamble(append_text: str, slug: Optional[str] = None, separator: str = "\n"):
    qs = FrontmanPersona.objects.all()
    persona = None
    if slug:
        persona = qs.filter(slug=slug).first()
    else:
        persona = qs.order_by("-created_at").first()
    if not persona:
        raise ValueError("No Frontman persona found to append to.")
    base = persona.postamble or ""
    sep = separator if base and separator is not None else ""
    persona.postamble = f"{base}{sep}{append_text}".strip()
    persona.save(update_fields=["postamble", "updated_at"])
    return {
        "slug": persona.slug,
        "name": persona.name,
        "instructions": persona.instructions,
        "postamble": persona.postamble or "",
        "is_active": persona.is_active,
    }


@register_function(
    manifest_id="frontman_admin.append_instructions",
    module="frontman_admin",
    description="Append text to a persona's main instructions (latest or by slug).",
    params_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Optional persona slug"},
            "append_text": {"type": "string", "description": "Text to append"},
            "separator": {
                "type": "string",
                "description": "Separator between existing and new text",
                "default": "\n",
            },
        },
        "required": ["append_text"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string"},
            "name": {"type": "string"},
            "instructions": {"type": "string"},
            "postamble": {"type": "string"},
            "is_active": {"type": "boolean"},
        },
    },
)
@transaction.atomic
def append_instructions(append_text: str, slug: Optional[str] = None, separator: str = "\n"):
    qs = FrontmanPersona.objects.all()
    persona = qs.filter(slug=slug).first() if slug else qs.order_by("-created_at").first()
    if not persona:
        raise ValueError("No Frontman persona found to append to.")
    base = persona.instructions or ""
    sep = separator if base and separator is not None else ""
    persona.instructions = f"{base}{sep}{append_text}".strip()
    persona.save(update_fields=["instructions", "updated_at"])
    return {
        "slug": persona.slug,
        "name": persona.name,
        "instructions": persona.instructions,
        "postamble": persona.postamble or "",
        "is_active": persona.is_active,
    }


@register_function(
    manifest_id="frontman_admin.set_active_persona",
    module="frontman_admin",
    description="Mark a persona as active (deactivates others).",
    params_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Persona slug to activate"},
        },
        "required": ["slug"],
    },
    return_schema={
        "type": "object",
        "properties": {"slug": {"type": "string"}, "name": {"type": "string"}, "is_active": {"type": "boolean"}},
    },
)
@transaction.atomic
def set_active_persona(slug: str):
    try:
        persona = FrontmanPersona.objects.get(slug=slug)
    except FrontmanPersona.DoesNotExist:
        raise ValueError(f"Persona '{slug}' not found")
    FrontmanPersona.objects.exclude(pk=persona.pk).update(is_active=False)
    persona.is_active = True
    persona.save(update_fields=["is_active", "updated_at"])
    return {"slug": persona.slug, "name": persona.name, "is_active": persona.is_active}
