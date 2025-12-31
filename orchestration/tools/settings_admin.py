from typing import Optional

from django.db import transaction

from orchestration.models import OrchestrationSetting
from orchestration.registry import register_function
from orchestration.services import ModelConfigService


ALLOWED_KEYS = {"frontman_model", "caller_model"}


def _validate_key(key: str):
    if key not in ALLOWED_KEYS:
        raise ValueError(f"Unsupported setting key '{key}'. Allowed: {sorted(ALLOWED_KEYS)}")


@register_function(
    manifest_id="settings_admin.list_settings",
    module="settings_admin",
    description="List configurable orchestration settings (frontman/caller models).",
    params_schema={"type": "object", "properties": {}},
    return_schema={
        "type": "object",
        "properties": {
            "settings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                },
            }
        },
    },
)
def list_settings():
    rows = []
    for key in sorted(ALLOWED_KEYS):
        rows.append({"key": key, "value": ModelConfigService.get_setting(key, "")})
    return {"settings": rows}


@register_function(
    manifest_id="settings_admin.get_setting",
    module="settings_admin",
    description="Get a single orchestration setting (frontman_model or caller_model).",
    params_schema={
        "type": "object",
        "properties": {"key": {"type": "string", "description": "Setting key (frontman_model or caller_model)"}},
        "required": ["key"],
    },
    return_schema={"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}},
)
def get_setting(key: str):
    _validate_key(key)
    return {"key": key, "value": ModelConfigService.get_setting(key, "")}


@register_function(
    manifest_id="settings_admin.set_setting",
    module="settings_admin",
    description="Set a single orchestration setting (frontman_model or caller_model).",
    params_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Setting key (frontman_model or caller_model)"},
            "value": {"type": "string", "description": "New model name/id"},
        },
        "required": ["key", "value"],
    },
    return_schema={"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}},
)
@transaction.atomic
def set_setting(key: str, value: str):
    _validate_key(key)
    OrchestrationSetting.objects.update_or_create(key=key, defaults={"value": value})
    return {"key": key, "value": value}
