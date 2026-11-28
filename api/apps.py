from django.apps import AppConfig


class ApiConfig(AppConfig):
    """SudoTag mobile REST API (django-ninja), mounted at /api/v1/."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'
    verbose_name = 'SudoTag API'
