import json
from typing import List, Optional

from django.db import transaction

from orchestration.crypto import decrypt_value, encrypt_value
from orchestration.models import ToolModule
from orchestration.registry import register_function


@register_function(
    manifest_id="module_admin.list_modules",
    module="module_admin",
    description="List modules with their caller instructions.",
    params_schema={"type": "object", "properties": {}},
    return_schema={
        "type": "object",
        "properties": {
            "modules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "name": {"type": "string"},
                        "caller_instructions": {"type": "string"},
                    },
                },
            }
        },
    },
)
def list_modules():
    modules = []
    for mod in ToolModule.objects.all().order_by("name"):
        modules.append(
            {
                "slug": mod.slug,
                "name": mod.name,
                "description": mod.description or "",
                "caller_instructions": mod.caller_instructions or "",
            }
        )
    return {"modules": modules}


@register_function(
    manifest_id="module_admin.get_instructions",
    module="module_admin",
    description="Get caller instructions for a module.",
    params_schema={
        "type": "object",
        "properties": {"module_slug": {"type": "string", "description": "Module slug"}},
        "required": ["module_slug"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string"},
            "caller_instructions": {"type": "string"},
        },
    },
)
def get_instructions(module_slug: str):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    return {"module_slug": module_slug, "caller_instructions": mod.caller_instructions or ""}


@register_function(
    manifest_id="module_admin.get_description",
    module="module_admin",
    description="Get description for a module.",
    params_schema={
        "type": "object",
        "properties": {"module_slug": {"type": "string", "description": "Module slug"}},
        "required": ["module_slug"],
    },
    return_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
        },
    },
)
def get_description(module_slug: str):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    return {"module_slug": module_slug, "name": mod.name, "description": mod.description or ""}


@register_function(
    manifest_id="module_admin.set_instructions",
    module="module_admin",
    description="Overwrite caller instructions for a module.",
    params_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string", "description": "Module slug"},
            "instructions": {"type": "string", "description": "New caller instructions"},
        },
        "required": ["module_slug", "instructions"],
    },
    return_schema={
        "type": "object",
        "properties": {"module_slug": {"type": "string"}, "caller_instructions": {"type": "string"}},
    },
)
@transaction.atomic
def set_instructions(module_slug: str, instructions: str):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    mod.caller_instructions = instructions
    mod.save(update_fields=["caller_instructions", "updated_at"])
    return {"module_slug": module_slug, "caller_instructions": mod.caller_instructions or ""}


@register_function(
    manifest_id="module_admin.set_description",
    module="module_admin",
    description="Overwrite description for a module.",
    params_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string", "description": "Module slug"},
            "description": {"type": "string", "description": "New description"},
        },
        "required": ["module_slug", "description"],
    },
    return_schema={
        "type": "object",
        "properties": {"module_slug": {"type": "string"}, "description": {"type": "string"}},
    },
)
@transaction.atomic
def set_description(module_slug: str, description: str):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    mod.description = description
    mod.save(update_fields=["description", "updated_at"])
    return {"module_slug": module_slug, "description": mod.description or ""}


@register_function(
    manifest_id="module_admin.append_instructions",
    module="module_admin",
    description="Append text to a module's caller instructions.",
    params_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string", "description": "Module slug"},
            "append_text": {"type": "string", "description": "Text to append"},
            "separator": {
                "type": "string",
                "description": "Separator between existing and new text",
                "default": " ",
            },
        },
        "required": ["module_slug", "append_text"],
    },
    return_schema={
        "type": "object",
        "properties": {"module_slug": {"type": "string"}, "caller_instructions": {"type": "string"}},
    },
)
@transaction.atomic
def append_instructions(module_slug: str, append_text: str, separator: str = " "):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    base = mod.caller_instructions or ""
    sep = separator if base and separator is not None else ""
    mod.caller_instructions = f"{base}{sep}{append_text}".strip()
    mod.save(update_fields=["caller_instructions", "updated_at"])
    return {"module_slug": module_slug, "caller_instructions": mod.caller_instructions or ""}


@register_function(
    manifest_id="module_admin.append_description",
    module="module_admin",
    description="Append text to a module's description.",
    params_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string", "description": "Module slug"},
            "append_text": {"type": "string", "description": "Text to append"},
            "separator": {
                "type": "string",
                "description": "Separator between existing and new text",
                "default": " ",
            },
        },
        "required": ["module_slug", "append_text"],
    },
    return_schema={
        "type": "object",
        "properties": {"module_slug": {"type": "string"}, "description": {"type": "string"}},
    },
)
@transaction.atomic
def append_description(module_slug: str, append_text: str, separator: str = " "):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    base = mod.description or ""
    sep = separator if base and separator is not None else ""
    mod.description = f"{base}{sep}{append_text}".strip()
    mod.save(update_fields=["description", "updated_at"])
    return {"module_slug": module_slug, "description": mod.description or ""}


def _load_secrets(mod: ToolModule) -> dict:
    if not mod.secrets_encrypted:
        return {}
    decrypted = decrypt_value(mod.secrets_encrypted)
    try:
        return json.loads(decrypted)
    except Exception:
        return {}


def _save_secrets(mod: ToolModule, secrets: dict):
    mod.secrets_encrypted = encrypt_value(json.dumps(secrets))
    mod.save(update_fields=["secrets_encrypted", "updated_at"])


@register_function(
    manifest_id="module_admin.get_secrets",
    module="module_admin",
    description="Get decrypted secrets for a module (entire dict or selected keys).",
    params_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string", "description": "Module slug"},
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of keys to return",
            },
        },
        "required": ["module_slug"],
    },
    return_schema={
        "type": "object",
        "properties": {"secrets": {"type": "object"}},
    },
)
def get_secrets(module_slug: str, keys: Optional[List[str]] = None):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    data = _load_secrets(mod)
    if keys:
        data = {k: v for k, v in data.items() if k in keys}
    return {"secrets": data}


@register_function(
    manifest_id="module_admin.set_secret",
    module="module_admin",
    description="Set or overwrite a secret key/value for a module (encrypted at rest).",
    params_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string", "description": "Module slug"},
            "key": {"type": "string", "description": "Secret key"},
            "value": {"type": "string", "description": "Secret value"},
        },
        "required": ["module_slug", "key", "value"],
    },
    return_schema={
        "type": "object",
        "properties": {"module_slug": {"type": "string"}, "keys": {"type": "array", "items": {"type": "string"}}},
    },
)
@transaction.atomic
def set_secret(module_slug: str, key: str, value: str):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    secrets = _load_secrets(mod)
    secrets[key] = value
    _save_secrets(mod, secrets)
    return {"module_slug": module_slug, "keys": list(secrets.keys())}


@register_function(
    manifest_id="module_admin.delete_secret",
    module="module_admin",
    description="Delete a secret key for a module.",
    params_schema={
        "type": "object",
        "properties": {
            "module_slug": {"type": "string", "description": "Module slug"},
            "key": {"type": "string", "description": "Secret key to delete"},
        },
        "required": ["module_slug", "key"],
    },
    return_schema={
        "type": "object",
        "properties": {"module_slug": {"type": "string"}, "keys": {"type": "array", "items": {"type": "string"}}},
    },
)
@transaction.atomic
def delete_secret(module_slug: str, key: str):
    try:
        mod = ToolModule.objects.get(slug=module_slug)
    except ToolModule.DoesNotExist:
        raise ValueError(f"Module '{module_slug}' not found")
    secrets = _load_secrets(mod)
    secrets.pop(key, None)
    _save_secrets(mod, secrets)
    return {"module_slug": module_slug, "keys": list(secrets.keys())}
