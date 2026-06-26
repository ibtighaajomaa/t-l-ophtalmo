import os
import sys

# Define settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Fix missing celery module just for the script to load settings
import sys
from unittest.mock import MagicMock
sys.modules['celery'] = MagicMock()
sys.modules['config.celery'] = MagicMock()

import django
django.setup()

from ophtalmo.models import Exam

print("Total exams:", Exam.objects.count())
print("En attente:", Exam.objects.filter(status='En attente').count())
print("En cours:", Exam.objects.filter(status='En cours').count())
