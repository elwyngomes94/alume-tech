from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.scheduling"
    label = "scheduling"
    verbose_name = "Agenda"

    def ready(self):  # pragma: no cover - registro de signals
        from . import signals  # noqa: F401
