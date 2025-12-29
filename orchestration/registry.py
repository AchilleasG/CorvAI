from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional


@dataclass
class RegisteredFunction:
    manifest_id: str
    module: str
    func: Callable
    name: Optional[str] = None
    description: Optional[str] = None
    params_schema: Optional[dict] = None
    return_schema: Optional[dict] = None
    deprecated: bool = False

    @property
    def handler_ref(self) -> str:
        return f"{self.func.__module__}.{self.func.__qualname__}"


class FunctionRegistry:
    """
    In-process registry of callable functions.
    The Function Runner uses this to resolve function ids to callables.
    """

    _registry: Dict[str, RegisteredFunction] = {}

    @classmethod
    def register(cls, entry: RegisteredFunction):
        if entry.manifest_id in cls._registry:
            raise ValueError(f"Function '{entry.manifest_id}' already registered")
        cls._registry[entry.manifest_id] = entry
        return entry

    @classmethod
    def get(cls, manifest_id: str) -> Optional[RegisteredFunction]:
        return cls._registry.get(manifest_id)

    @classmethod
    def all(cls):
        return list(cls._registry.values())

    @classmethod
    def resolve_callable(cls, manifest_id: str) -> Callable:
        entry = cls.get(manifest_id)
        if not entry:
            raise KeyError(f"Function '{manifest_id}' not registered")
        return entry.func


def register_function(
    *,
    manifest_id: str,
    module: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    params_schema: Optional[dict] = None,
    return_schema: Optional[dict] = None,
    deprecated: bool = False,
):
    """
    Decorator to register a callable as a tool function.

    Usage:
        @register_function(manifest_id="calendar.create_event", module="calendar")
        def create_event(...):
            ...
    """

    def decorator(func: Callable):
        entry = RegisteredFunction(
            manifest_id=manifest_id,
            module=module,
            func=func,
            name=name or manifest_id,
            description=description or "",
            params_schema=params_schema,
            return_schema=return_schema,
            deprecated=deprecated,
        )
        FunctionRegistry.register(entry)
        return func

    return decorator


def sync_registry_to_db():
    """
    Sync the in-process registry to the DB manifests.
    Should be called at startup or via a management command.
    """
    from django.db import transaction
    from orchestration.models import ToolFunction, ToolModule

    with transaction.atomic():
        for entry in FunctionRegistry.all():
            module_obj, _ = ToolModule.objects.get_or_create(
                slug=entry.module,
                defaults={"name": entry.module, "description": ""},
            )
            defaults = {
                "module": module_obj,
                "name": entry.name or entry.manifest_id,
                "description": entry.description or "",
                "params_schema": entry.params_schema or {},
                "return_schema": entry.return_schema or {},
                "tags": [],
                "deprecated": entry.deprecated,
                "handler_ref": entry.handler_ref,
            }
            ToolFunction.objects.update_or_create(
                manifest_id=entry.manifest_id,
                defaults=defaults,
            )
