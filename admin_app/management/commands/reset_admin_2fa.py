"""Reset an admin's personal password + authenticator (lost phone, forgotten
password). Their next sign-in uses the shared ADMIN_PANEL_PASSWORD once and
goes straight to setup again.

    python3 manage.py reset_admin_2fa someone@example.com
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Reset an admin's personal password and authenticator so they set them up again."

    def add_arguments(self, parser):
        parser.add_argument('email')

    def handle(self, *args, **opts):
        from firebase_admin import firestore
        from google.cloud.firestore_v1.base_query import FieldFilter
        from admin_app.admin_security import ACCOUNTS
        from admin_app.views import db

        email = opts['email'].strip()
        uids = set()
        for value in {email, email.lower()}:
            for doc in db.collection('users').where(filter=FieldFilter('emailAddress', '==', value)).stream():
                uids.add(doc.id)
        if not uids:
            raise CommandError(f'No user with email {email}.')
        for uid in uids:
            db.collection(ACCOUNTS).document(uid).set({
                'passwordHash': firestore.DELETE_FIELD,
                'totpSecretEnc': firestore.DELETE_FIELD,
                'totpEnabled': False,
                'lastTotpStep': firestore.DELETE_FIELD,
                'resetAt': firestore.SERVER_TIMESTAMP,
            }, merge=True)
        self.stdout.write(self.style.SUCCESS(
            f'Reset {email}. They sign in once with the shared password, then set up a new password and authenticator.'))
