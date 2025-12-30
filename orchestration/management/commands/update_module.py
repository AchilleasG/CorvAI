from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from orchestration.models import ToolModule


class Command(BaseCommand):
    help = "Update ToolModule metadata (name, description, caller instructions)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="Module slug to update (e.g., calendar)")
        parser.add_argument("--name", help="Display name (optional)")
        parser.add_argument("--description", help="Description (optional)")
        parser.add_argument(
            "--caller-instructions",
            help="Hints for Function Caller planning (optional)",
        )
        parser.add_argument(
            "--append-caller-instructions",
            help="Append text to existing caller instructions (separated by a space)",
        )
        parser.add_argument(
            "--show",
            action="store_true",
            help="Show current metadata before applying updates (or only show if no updates given)",
        )

    def handle(self, *args, **options):
        slug = options["slug"]
        name = options.get("name")
        description = options.get("description")
        caller_instructions = options.get("caller_instructions")
        append_caller_instructions = options.get("append_caller_instructions")

        try:
            module = ToolModule.objects.get(slug=slug)
        except ToolModule.DoesNotExist:
            raise CommandError(f"Module '{slug}' not found")

        updated_fields = []

        if options["show"]:
            self.stdout.write(
                f"Current module '{slug}':\n"
                f"  name: {module.name}\n"
                f"  description: {module.description}\n"
                f"  caller_instructions: {module.caller_instructions}"
            )
            # If no updates provided, exit after showing.
            if name is None and description is None and caller_instructions is None:
                return
        if name is not None and name != module.name:
            module.name = name
            updated_fields.append("name")
        if description is not None and description != module.description:
            module.description = description
            updated_fields.append("description")
        if append_caller_instructions:
            new_val = (module.caller_instructions or "").strip()
            if new_val and not new_val.endswith(" "):
                new_val += " "
            new_val += append_caller_instructions.strip()
            if new_val != module.caller_instructions:
                module.caller_instructions = new_val
                updated_fields.append("caller_instructions")
        elif caller_instructions is not None and caller_instructions != module.caller_instructions:
            module.caller_instructions = caller_instructions
            updated_fields.append("caller_instructions")

        if not updated_fields:
            self.stdout.write(self.style.WARNING("No changes to apply"))
            return

        module.save(update_fields=updated_fields)
        self.stdout.write(self.style.SUCCESS(f"Updated module '{slug}': {', '.join(updated_fields)}"))
