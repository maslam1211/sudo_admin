from django.apps import AppConfig


class PartnersConfig(AppConfig):
    """Partner Programme data copied from Firestore (Phase 3, read side)."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'partners'
