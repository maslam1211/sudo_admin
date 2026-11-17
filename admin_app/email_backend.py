import ssl

import certifi
from django.core.mail.backends.smtp import EmailBackend as SmtpEmailBackend


class CustomEmailBackend(SmtpEmailBackend):
    """SMTP backend that verifies the mail server's certificate.

    Uses certifi's CA bundle, so it also works on Python installs that ship
    without system certificates (python.org builds on macOS).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
