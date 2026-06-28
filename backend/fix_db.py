import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from ophtalmo.models import Exam
from users.models import Profil

exams = Exam.objects.filter(status='En cours')
c = 0
for e in exams:
    e.status = 'En attente'
    e.assigned_to = None
    e.date_assignation = None
    e.save(update_fields=['status', 'assigned_to', 'date_assignation'])
    c += 1

for p in Profil.objects.all():
    p.charge_actuelle = 0
    p.save(update_fields=['charge_actuelle'])

print(f"{c} examens remis en attente")
