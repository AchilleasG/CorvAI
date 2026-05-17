from django.apps import AppConfig


class StudyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "study"
    verbose_name = "Study"

    def ready(self):
        from . import tools  # noqa: F401
        from . import signals  # noqa: F401
