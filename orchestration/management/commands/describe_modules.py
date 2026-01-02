from __future__ import annotations

from django.core.management.base import BaseCommand

from orchestration.models import ToolFunction, ToolModule


class Command(BaseCommand):
    help = "Print tool modules and their functions (metadata inspection)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--module",
            help="Slug of a specific module to describe (omit to list all)",
        )

    def handle(self, *args, **options):
        module_slug = options.get("module")

        modules = (
            ToolModule.objects.filter(slug=module_slug)
            if module_slug
            else ToolModule.objects.all().order_by("name")
        )

        if module_slug and not modules.exists():
            self.stdout.write(self.style.ERROR(f"Module '{module_slug}' not found"))
            return

        for mod in modules:
            self.stdout.write(
                f"[{mod.slug}] name='{mod.name}'\n"
                f"  description: {mod.description or '(empty)'}\n"
                f"  caller_instructions: {mod.caller_instructions or '(empty)'}\n"
                f"  tags: {mod.tags or []}"
            )
            funcs = ToolFunction.objects.filter(module=mod).order_by("manifest_id")
            if not funcs:
                self.stdout.write("  (no functions)")
            for func in funcs:
                self.stdout.write(
                    f"  - {func.manifest_id} | deprecated={func.deprecated}\n"
                    f"    name: {func.name}\n"
                    f"    desc: {func.description}\n"
                    f"    handler: {func.handler_ref}\n"
                    f"    params_schema keys: {list((func.params_schema or {}).get('properties', {}).keys())}"
                )
            self.stdout.write("")
