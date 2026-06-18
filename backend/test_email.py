import os
import django
from django.core.mail import send_mail
from django.conf import settings
import ssl

# Setup minimal Django settings
if not settings.configured:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

def _create_unverified_context(*args, **kwargs):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
ssl.create_default_context = _create_unverified_context

try:
    print("Sending email...")
    send_mail(
        'Test Subject',
        'Test Message',
        settings.DEFAULT_FROM_EMAIL,
        ['tele.ophtalmo@rns.tn'],  # Send to self to test
        fail_silently=False,
    )
    print("Email sent successfully!")
except Exception as e:
    print(f"Error sending email: {e}")
