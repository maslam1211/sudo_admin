"""Firebase Trigger Email backend: message mapping and queuing."""
from unittest import mock

from django.core import mail
from django.core.mail import EmailMultiAlternatives, send_mail
from django.test import SimpleTestCase, override_settings

from admin_app import firestore_email_backend as feb

BACKEND = 'admin_app.firestore_email_backend.FirestoreEmailBackend'


class MappingTests(SimpleTestCase):
    def test_text_and_html(self):
        msg = EmailMultiAlternatives('Hi', 'plain', 'from@x.com', ['a@x.com'], cc=['c@x.com'],
                                     bcc=['b@x.com'], reply_to=['r@x.com'])
        msg.attach_alternative('<b>html</b>', 'text/html')
        doc = feb.message_to_doc(msg)
        self.assertEqual(doc['to'], ['a@x.com'])
        self.assertEqual(doc['cc'], ['c@x.com'])
        self.assertEqual(doc['bcc'], ['b@x.com'])
        self.assertEqual(doc['from'], 'from@x.com')
        self.assertEqual(doc['replyTo'], 'r@x.com')
        self.assertEqual(doc['message'], {'subject': 'Hi', 'text': 'plain', 'html': '<b>html</b>'})

    def test_html_only_body(self):
        msg = mail.EmailMessage('S', '<p>x</p>', 'f@x.com', ['a@x.com'])
        msg.content_subtype = 'html'
        self.assertEqual(feb.message_to_doc(msg)['message'], {'subject': 'S', 'html': '<p>x</p>'})


@override_settings(EMAIL_BACKEND=BACKEND, FIREBASE_MAIL_COLLECTION='mail')
class SendTests(SimpleTestCase):
    def _patch(self):
        collection = mock.Mock()
        client = mock.Mock()
        client.collection.return_value = collection
        return collection, mock.patch('firebase_admin.firestore.client', return_value=client), \
            mock.patch('admin_app.firebase_init.ensure_firebase_app')

    def test_send_mail_queues_document(self):
        collection, p_client, p_app = self._patch()
        with p_client, p_app:
            sent = send_mail('Subj', 'Body', 'from@x.com', ['to@x.com'], html_message='<p>Body</p>')
        self.assertEqual(sent, 1)
        doc = collection.add.call_args[0][0]
        self.assertEqual(doc['to'], ['to@x.com'])
        self.assertEqual(doc['message']['html'], '<p>Body</p>')
        self.assertIn('createdAt', doc)

    def test_errors_raise_unless_silent(self):
        collection, p_client, p_app = self._patch()
        collection.add.side_effect = RuntimeError('down')
        with p_client, p_app:
            with self.assertRaises(RuntimeError):
                send_mail('S', 'B', 'f@x.com', ['t@x.com'])
            self.assertEqual(send_mail('S', 'B', 'f@x.com', ['t@x.com'], fail_silently=True), 0)
