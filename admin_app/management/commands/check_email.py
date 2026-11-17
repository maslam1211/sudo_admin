"""
Diagnose outgoing email on this server.

    python manage.py check_email                 # config + Gmail login only
    python manage.py check_email you@example.com # also send one test email

With EMAIL_DELIVERY=firebase it queues the test email in Firestore instead and
waits for the Trigger Email extension to report SUCCESS or ERROR.

Prints which step fails, without ever printing the password.
"""
import os
import socket
import time

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Check that this server can log in to the SMTP server and send email.'

    def add_arguments(self, parser):
        parser.add_argument('to', nargs='?', help='Optional address to send a test email to')

    def handle(self, *args, **options):
        ok = self.style.SUCCESS
        bad = self.style.ERROR
        if getattr(settings, 'EMAIL_DELIVERY', 'smtp') == 'firebase':
            return self._check_firebase(options.get('to'), ok, bad)
        password = settings.EMAIL_HOST_PASSWORD or ''

        self.stdout.write(f'Settings file DEBUG     : {settings.DEBUG}')
        self.stdout.write(f'SMTP host / port        : {settings.EMAIL_HOST}:{settings.EMAIL_PORT}')
        self.stdout.write(f'Login user              : {settings.EMAIL_HOST_USER}')
        source = '.env / environment' if os.getenv('EMAIL_HOST_PASSWORD') else 'not set (add EMAIL_HOST_PASSWORD to .env)'
        self.stdout.write(f'Password comes from     : {source}')
        letters = len(password.replace(' ', ''))
        line = f'Password length         : {letters} letters (Gmail app passwords have 16)'
        self.stdout.write(ok(line) if letters == 16 else bad(line))
        if getattr(settings, 'ACTIVATION_DUMMY_EMAIL_OTP', ''):
            self.stdout.write(bad('ACTIVATION_DUMMY_EMAIL_OTP is set: remove it on the live server!'))

        # 1. Can this server reach Gmail at all? (Some hosts block SMTP ports.)
        try:
            socket.create_connection((settings.EMAIL_HOST, settings.EMAIL_PORT), timeout=10).close()
            self.stdout.write(ok('Network to SMTP server  : OK'))
        except OSError as exc:
            self.stdout.write(bad(f'Network to SMTP server  : BLOCKED ({exc})'))
            self.stdout.write('  -> Your hosting provider blocks outgoing SMTP on this port. '
                              'Ask them to open port 587, or use an email API service.')
            return

        # 2. Does Gmail accept the login?
        conn = get_connection()
        try:
            conn.open()
            conn.close()
            self.stdout.write(ok('Gmail login             : OK'))
        except Exception as exc:
            self.stdout.write(bad(f'Gmail login             : FAILED ({type(exc).__name__}: {exc})'))
            self.stdout.write('  -> Put a valid 16-letter Gmail App Password in .env as '
                              'EMAIL_HOST_PASSWORD=..., then restart the server.')
            return

        # 3. Optional real send.
        to = options.get('to')
        if to:
            try:
                send_mail('SudoTag email test', 'Email from this server works.',
                          settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
                self.stdout.write(ok(f'Test email sent to      : {to}'))
            except Exception as exc:
                self.stdout.write(bad(f'Test email              : FAILED ({type(exc).__name__}: {exc})'))

    def _check_firebase(self, to, ok, bad):
        from firebase_admin import firestore

        from admin_app.firebase_init import ensure_firebase_app
        from admin_app.firestore_email_backend import mail_collection

        app = ensure_firebase_app()
        self.stdout.write(f'Delivery                : Firebase Trigger Email ({app.project_id}/{mail_collection()})')
        if not to:
            self.stdout.write('Pass an address to queue a test email, e.g. check_email you@example.com')
            return
        db = firestore.client(app)
        _, ref = db.collection(mail_collection()).add({
            'to': [to],
            'from': settings.DEFAULT_FROM_EMAIL,
            'message': {'subject': 'SudoTag email test', 'text': 'Email through Firebase works.'},
            'createdAt': firestore.SERVER_TIMESTAMP,
        })
        self.stdout.write(f'Queued                  : {mail_collection()}/{ref.id}')
        for _ in range(30):
            time.sleep(2)
            delivery = (ref.get().to_dict() or {}).get('delivery') or {}
            state = delivery.get('state')
            if state == 'SUCCESS':
                self.stdout.write(ok(f'Test email sent to      : {to}'))
                return
            if state == 'ERROR':
                self.stdout.write(bad(f'Extension error         : {delivery.get("error")}'))
                return
        self.stdout.write(bad('No delivery result after 60s: is the Trigger Email extension installed '
                              f'and watching the "{mail_collection()}" collection?'))
