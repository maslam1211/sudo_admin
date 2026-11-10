"""
Find customer profiles whose Firebase Auth login no longer exists and restore it.

Earlier web activations could fail after emailing a password and then delete the
login, leaving a profile (and often an activated vehicle QR) the customer cannot
sign in to. This recreates the login with the profile's own document id as uid,
so existing vehicles and QRs stay linked, and emails a new password.

    python manage.py repair_missing_logins            # list only (dry run)
    python manage.py repair_missing_logins --apply    # recreate + email password
    python manage.py repair_missing_logins --apply --email someone@example.com
"""
from django.core.management.base import BaseCommand
from firebase_admin import auth

from admin_app import views


class Command(BaseCommand):
    help = 'Restore missing Firebase Auth logins for customer profiles (dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Recreate logins and email passwords.')
        parser.add_argument('--email', help='Only repair this email address.')

    def handle(self, *args, apply=False, email=None, **options):
        only = (email or '').strip().lower() or None
        candidates = []
        for snap in views.db.collection('users').stream():
            data = snap.to_dict() or {}
            addr = str(data.get('emailAddress') or '').strip().lower()
            if not addr or views._is_admin_role_id(data.get('roleId')):
                continue
            if data.get('purpose') == views.MULTIPURPOSE_CALL_BRIDGE_PURPOSE:
                continue
            if only and addr != only:
                continue
            candidates.append((snap.id, addr, data))

        missing = []
        for i in range(0, len(candidates), 100):
            chunk = candidates[i:i + 100]
            result = auth.get_users([auth.EmailIdentifier(addr) for _, addr, _ in chunk])
            not_found = {ident.email.lower() for ident in result.not_found}
            missing.extend(c for c in chunk if c[1] in not_found)

        if not missing:
            self.stdout.write(self.style.SUCCESS('No profiles with a missing login.'))
            return

        self.stdout.write(f'{len(missing)} profile(s) without a login:')
        for doc_id, addr, data in missing:
            self.stdout.write(f'  {doc_id}  {addr}  {data.get("fullName") or ""}')

        if not apply:
            self.stdout.write('Dry run. Re-run with --apply to restore these logins.')
            return

        fixed = 0
        for doc_id, addr, data in missing:
            name = data.get('fullName') or ''
            try:
                _, password = views._recreate_login_for_profile(doc_id, addr, name)
            except auth.UidAlreadyExistsError:
                self.stderr.write(f'  SKIP {addr}: uid {doc_id} already used by another login')
                continue
            except Exception as exc:
                self.stderr.write(f'  FAIL {addr}: {exc}')
                continue
            try:
                views.send_welcome_email_for_id(email=addr, name=name, password=password)
                self.stdout.write(self.style.SUCCESS(f'  restored {addr} (password emailed)'))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f'  restored {addr} but email failed ({exc}); temporary password: {password}'
                ))
            fixed += 1
        self.stdout.write(self.style.SUCCESS(f'Restored {fixed} login(s).'))
