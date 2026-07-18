from django.apps import AppConfig


class OphtalmoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ophtalmo'

    def ready(self):
        from . import signals  # noqa: F401
