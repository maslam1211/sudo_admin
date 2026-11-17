"""
Django email backend that sends through Firebase's "Trigger Email from Firestore"
extension (firebase/firestore-send-email) on project sudotag-faa80.

Each message becomes a document in the mail collection (FIREBASE_MAIL_COLLECTION,
default "mail"); the extension picks it up, sends it through the SMTP service it was
installed with, and writes the result back into the document's ``delivery`` field
(state PENDING -> PROCESSING -> SUCCESS / ERROR).

Turn it on with EMAIL_DELIVERY=firebase in .env. Every send_mail() in the app then
goes through Firebase without code changes.

Note: send_mail() returns as soon as the document is written. A wrong address or
an SMTP problem shows up later in the document's delivery.error, not as an exception.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


def mail_collection() -> str:
    return getattr(settings, 'FIREBASE_MAIL_COLLECTION', '') or 'mail'


def message_to_doc(message) -> dict:
    """Map a Django EmailMessage to the extension's document format."""
    html = None
    for content, mimetype in getattr(message, 'alternatives', None) or []:
        if mimetype == 'text/html':
            html = content
            break
    if html is None and getattr(message, 'content_subtype', '') == 'html':
        html = message.body
        text = None
    else:
        text = message.body or None

    doc = {
        'to': list(message.to),
        'message': {'subject': message.subject or ''},
    }
    if text:
        doc['message']['text'] = text
    if html:
        doc['message']['html'] = html
    if message.cc:
        doc['cc'] = list(message.cc)
    if message.bcc:
        doc['bcc'] = list(message.bcc)
    if message.from_email:
        doc['from'] = message.from_email
    if message.reply_to:
        doc['replyTo'] = message.reply_to[0] if len(message.reply_to) == 1 else list(message.reply_to)
    if getattr(message, 'attachments', None):
        logger.warning('Firebase email backend drops %d attachment(s) on "%s"',
                       len(message.attachments), message.subject)
    return doc


class FirestoreEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        from firebase_admin import firestore

        from .firebase_init import ensure_firebase_app

        sent = 0
        try:
            db = firestore.client(ensure_firebase_app())
            collection = db.collection(mail_collection())
        except Exception:
            logger.exception('Firebase email backend could not reach Firestore')
            if not self.fail_silently:
                raise
            return 0

        for message in email_messages:
            if not message.recipients():
                continue
            try:
                doc = message_to_doc(message)
                doc['createdAt'] = firestore.SERVER_TIMESTAMP
                collection.add(doc)
                sent += 1
            except Exception:
                logger.exception('Queuing email "%s" in Firestore failed', message.subject)
                if not self.fail_silently:
                    raise
        return sent
