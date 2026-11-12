"""
Diagnose outgoing email on this server.

    python manage.py check_email                 # config + Gmail login only
    python manage.py check_email you@example.com # also send one test email

Prints which step fails, without ever printing the password.
"""
import os
import socket

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
        password = settings.EMAIL_HOST_PASSWORD or ''

        self.stdout.write(f'Settings file DEBUG     : {settings.DEBUG}')
        self.stdout.write(f'SMTP host / port        : {settings.EMAIL_HOST}:{settings.EMAIL_PORT}')
        self.stdout.write(f'Login user              : {settings.EMAIL_HOST_USER}')
        source = '.env / environment' if os.getenv('EMAIL_HOST_PASSWORD') else 'OLD value inside settings.py'
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
