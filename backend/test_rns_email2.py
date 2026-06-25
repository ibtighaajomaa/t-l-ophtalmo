import os
import django
import smtplib
import ssl
from django.core.mail import send_mail
from django.core.mail.backends.smtp import EmailBackend

class UnverifiedEmailBackend(EmailBackend):
    @property
    def ssl_context(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['EMAIL_HOST'] = '193.95.84.21'
os.environ['EMAIL_PORT'] = '587'
os.environ['EMAIL_HOST_USER'] = 'tele.ophtalmo'
os.environ['EMAIL_HOST_PASSWORD'] = 'pohvbW2@'
os.environ['EMAIL_USE_TLS'] = 'True'
os.environ['DEFAULT_FROM_EMAIL'] = 'tele.ophtalmo@rns.tn'

django.setup()

try:
    from django.core.mail import get_connection
    conn = get_connection(backend='test_rns_email2.UnverifiedEmailBackend')
    send_mail(
        'Subject here',
        'Here is the message.',
        'tele.ophtalmo@rns.tn',
        ['test@example.com'],
        fail_silently=False,
        connection=conn,
    )
    print("Django send_mail succeeded!")
except Exception as e:
    print("Django send_mail failed:", repr(e))
