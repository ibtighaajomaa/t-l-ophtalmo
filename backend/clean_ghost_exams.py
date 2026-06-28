import os
import django
import requests

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from ophtalmo.models import Exam, CalendarSession
from users.models import Profil

ORTHANC_URL = os.environ.get('ORTHANC_URL', 'http://orthanc-container:8042')

try:
    resp = requests.get(f'{ORTHANC_URL}/studies', timeout=30)
    resp.raise_for_status()
    study_ids = set(resp.json())
except Exception as e:
    print(f"Error fetching from Orthanc: {e}")
    exit(1)

all_exams = Exam.objects.all()
ghost_exams = []
for exam in all_exams:
    if exam.study_instance_uid not in study_ids:
        ghost_exams.append(exam)

print(f"Found {len(ghost_exams)} ghost exams out of {all_exams.count()} total.")

for exam in ghost_exams:
    exam.delete()

print(f"Deleted {len(ghost_exams)} ghost exams.")

# Reset profiles
for p in Profil.objects.all():
    p.charge_actuelle = 0
    p.save(update_fields=['charge_actuelle'])

print("Cleaned up profiles.")
