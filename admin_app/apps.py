import os
import sys

from django.apps import AppConfig


class AdminAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'admin_app'

    def ready(self):
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return
        from django.conf import settings

        # Management commands (migrate, test, run_worker, mirror_firestore …)
        # must not start a push loop; the worker runs schedules itself.
        is_command = (
            len(sys.argv) > 1
            and sys.argv[0].endswith('manage.py')
            and sys.argv[1] != 'runserver'
        )
        if is_command or not getattr(settings, 'SCHEDULED_PUSH_IN_WEB', True):
            return
        from .scheduled_push import start_scheduler
        start_scheduler()
