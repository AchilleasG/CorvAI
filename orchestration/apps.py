from django.apps import AppConfig
import importlib
import pkgutil
import pathlib


def _import_tool_modules():
    """
    Auto-import all Python files under orchestration.tools so decorators register.
    """
    pkg_path = pathlib.Path(__file__).resolve().parent / "tools"
    if not pkg_path.exists():
        return
    for module_info in pkgutil.iter_modules([str(pkg_path)]):
        if module_info.name.startswith("_"):
            continue
        importlib.import_module(f"orchestration.tools.{module_info.name}")


class OrchestrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "orchestration"
    verbose_name = "Corv Orchestration"

    def ready(self):
        # Register decorated functions at startup.
        _import_tool_modules()
