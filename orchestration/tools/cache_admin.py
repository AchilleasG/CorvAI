from typing import Optional

from django.db import transaction

from orchestration.registry import register_function
from orchestration.services import ModelConfigService


ALLOWED_CACHE_MODES = {"off", "frontman", "caller", "all"}


def _validate_mode(mode: str):
    mode = (mode or "").lower()
    if mode not in ALLOWED_CACHE_MODES:
        raise ValueError(f"Unsupported cache_mode '{mode}'. Allowed: {sorted(ALLOWED_CACHE_MODES)}")
    return mode


@register_function(
    manifest_id="cache_admin.get_cache_mode",
    module="cache_admin",
    description="Get current cache mode (off/frontman/caller/all).",
    params_schema={"type": "object", "properties": {}},
    return_schema={"type": "object", "properties": {"cache_mode": {"type": "string"}}},
)
def get_cache_mode():
    return {"cache_mode": ModelConfigService.get_cache_mode()}


@register_function(
    manifest_id="cache_admin.set_cache_mode",
    module="cache_admin",
    description="Set cache mode (off/frontman/caller/all).",
    params_schema={
        "type": "object",
        "properties": {"cache_mode": {"type": "string", "description": "off|frontman|caller|all"}},
        "required": ["cache_mode"],
    },
    return_schema={"type": "object", "properties": {"cache_mode": {"type": "string"}}},
)
@transaction.atomic
def set_cache_mode(cache_mode: str):
    mode = _validate_mode(cache_mode)
    ModelConfigService.set_setting("cache_mode", mode)
    return {"cache_mode": mode}
