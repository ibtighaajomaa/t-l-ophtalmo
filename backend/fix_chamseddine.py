import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from ophtalmo.models import Exam, CalendarSession

# Soft delete chamseddine@gmail.com
user = User.objects.filter(username='chamseddine@gmail.com').first()
if user:
    user.is_active = False
    user.save()
    if hasattr(user, 'profil'):
        user.profil.is_disponible = False
        user.profil.save()
    
    # Remove exams
    exams = Exam.objects.filter(assigned_to=user)
    if exams.exists():
        exams.update(status='En attente', assigned_to=None, date_assignation=None)
    
    # Remove future sessions (and today's)
    from datetime import date
    CalendarSession.objects.filter(doctor=user, date__gte=date.today()).delete()
    print("Cleaned up chamseddine@gmail.com")
else:
    print("User not found")
