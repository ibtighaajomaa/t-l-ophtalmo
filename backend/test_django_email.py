import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.core.mail import send_mail

try:
    send_mail(
        'Subject here',
        'Here is the message.',
        'tele.ophtalmo@rns.tn',
        ['test@example.com'],
        fail_silently=False,
    )
    print("Django send_mail succeeded!")
except Exception as e:
    print("Django send_mail failed:", repr(e))
