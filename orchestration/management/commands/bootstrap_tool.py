from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from orchestration.models import ToolFunction, ToolModule


TEMPLATE = """\
from orchestration.registry import register_function


@register_function(
    manifest_id="{manifest_id}",
    module="{module_slug}",
    name="{name}",
    description="{description}",
    params_schema={params_schema},
    return_schema={return_schema},
    deprecated={deprecated},
)
def {function_name}({params_signature}):
    \"\"\"{description}\"\"\"
    # TODO: implement {manifest_id}
    raise NotImplementedError("{manifest_id}")
"""


class Command(BaseCommand):
    help = "Bootstrap a tool module/function with DB metadata and a decorator stub."

    def add_arguments(self, parser):
        parser.add_argument("--module-slug", required=True, help="Module slug (e.g., calendar)")
        parser.add_argument("--module-name", default=None, help="Display name; defaults to slug")
        parser.add_argument("--module-description", default="", help="Module description")
        parser.add_argument(
            "--module-caller-instructions",
            default="",
            help="Hints for the Function Caller when planning tools in this module",
        )
        parser.add_argument("--manifest-id", required=True, help="Function manifest id (e.g., calendar.create_event)")
        parser.add_argument("--function-name", required=False, help="Python function name; defaults to last segment of manifest id")
        parser.add_argument("--function-description", default="", help="Function description")
        parser.add_argument("--params-schema", default="{}", help="JSON string for params schema")
        parser.add_argument("--return-schema", default="{}", help="JSON string for return schema")
        parser.add_argument(
            "--target-file",
            default=None,
            help="File to write stub into; default orchestration/tools/<module>.py",
        )
        parser.add_argument(
            "--params-signature",
            default="**kwargs",
            help="Python signature to use in the stub (e.g., title: str, start: str)",
        )
        parser.add_argument(
            "--deprecated",
            action="store_true",
            help="Mark function as deprecated",
        )

    def handle(self, *args, **options):
        module_slug: str = options["module_slug"]
        module_name: str = options["module_name"] or module_slug
        module_description: str = options["module_description"]
        module_caller_instructions: str = options["module_caller_instructions"]
        manifest_id: str = options["manifest_id"]
        function_name: str = options.get("function_name") or manifest_id.split(".")[-1]
        function_description: str = options["function_description"] or ""
        params_schema_raw: str = options["params_schema"]
        return_schema_raw: str = options["return_schema"]
        params_signature: str = options["params_signature"]
        deprecated: bool = options["deprecated"]

        try:
            params_schema: Dict[str, Any] = json.loads(params_schema_raw)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid params schema JSON: {exc}")

        try:
            return_schema: Dict[str, Any] = json.loads(return_schema_raw)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid return schema JSON: {exc}")

        target_file: Optional[str] = options["target_file"]
        if not target_file:
            target_file = f"orchestration/tools/{module_slug}.py"

        stub_path = Path(target_file)
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        if stub_path.exists():
            existing = stub_path.read_text(encoding="utf-8")
            if manifest_id in existing:
                self.stdout.write(self.style.WARNING(f"Stub already contains {manifest_id}; skipping write"))
            else:
                with stub_path.open("a", encoding="utf-8") as fh:
                    fh.write("\n\n" + TEMPLATE.format(
                        manifest_id=manifest_id,
                        module_slug=module_slug,
                        name=manifest_id,
                        description=function_description.replace('"', '\\"'),
                        params_schema=json.dumps(params_schema, indent=2),
                        return_schema=json.dumps(return_schema, indent=2),
                        deprecated="True" if deprecated else "False",
                        function_name=function_name,
                        params_signature=params_signature,
                    ))
                self.stdout.write(self.style.SUCCESS(f"Appended stub to {stub_path}"))
        else:
            stub_path.write_text(
                TEMPLATE.format(
                    manifest_id=manifest_id,
                    module_slug=module_slug,
                    name=manifest_id,
                    description=function_description.replace('"', '\\"'),
                    params_schema=json.dumps(params_schema, indent=2),
                    return_schema=json.dumps(return_schema, indent=2),
                    deprecated="True" if deprecated else "False",
                    function_name=function_name,
                    params_signature=params_signature,
                ),
                encoding="utf-8",
            )
            self.stdout.write(self.style.SUCCESS(f"Created stub at {stub_path}"))

        dotted_module = stub_path.with_suffix("").as_posix().replace("/", ".")
        handler_ref = f"{dotted_module}.{function_name}"

        with transaction.atomic():
            module_obj, _ = ToolModule.objects.get_or_create(
                slug=module_slug,
                defaults={
                    "name": module_name,
                    "description": module_description,
                    "caller_instructions": module_caller_instructions,
                },
            )
            if (
                module_obj.name != module_name
                or module_obj.description != module_description
                or module_obj.caller_instructions != module_caller_instructions
            ):
                module_obj.name = module_name
                module_obj.description = module_description
                module_obj.caller_instructions = module_caller_instructions
                module_obj.save(update_fields=["name", "description", "caller_instructions"])

            func_defaults = {
                "module": module_obj,
                "name": manifest_id,
                "description": function_description,
                "params_schema": params_schema,
                "return_schema": return_schema,
                "tags": [],
                "deprecated": deprecated,
                "handler_ref": handler_ref,
            }
            func_obj, created = ToolFunction.objects.update_or_create(
                manifest_id=manifest_id,
                defaults=func_defaults,
            )

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} DB manifest for {manifest_id}"))
        self.stdout.write(
            f"Next: implement {handler_ref} and import orchestration.tools.* somewhere on startup so the decorator registers."
        )
