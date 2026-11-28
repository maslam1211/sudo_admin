from django.apps import AppConfig


class CivicConfig(AppConfig):
    """CivicSense data copied from Firestore (Phase 3, read side)."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'civic'
