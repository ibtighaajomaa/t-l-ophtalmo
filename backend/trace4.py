import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.utils import timezone
from datetime import datetime

today = timezone.localdate()
print("today:", today)

date_str = '2026-06-29'
session_date = datetime.strptime(date_str, '%Y-%m-%d').date()
print("session_date:", session_date)
print("session_date == today:", session_date == today)
