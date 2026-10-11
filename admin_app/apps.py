import os
import sys

from django.apps import AppConfig


class AdminAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'admin_app'

    def ready(self):
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return
        from .scheduled_push import start_scheduler
        start_scheduler()
