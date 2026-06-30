import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from ophtalmo.models import Exam
from users.models import Profil

inactive_users = User.objects.filter(is_active=False)

for user in inactive_users:
    if hasattr(user, 'profil'):
        user.profil.is_disponible = False
        user.profil.charge_actuelle = 0
        user.profil.save()
    
    exams = Exam.objects.filter(assigned_to=user, status__in=['En cours', 'En attente'])
    count = exams.count()
    if count > 0:
        print(f"Unassigning {count} exams from {user.username}")
        exams.update(status='En attente', assigned_to=None, date_assignation=None)

from ophtalmo.distribution import distribuer_examens
distribuer_examens()
print("Done")
