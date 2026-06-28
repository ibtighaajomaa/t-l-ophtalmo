import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from ophtalmo.models import Exam, CalendarSession

print(f"Total exams: {Exam.objects.count()}")
print(f"En attente: {Exam.objects.filter(status='En attente').count()}")
print(f"En cours: {Exam.objects.filter(status='En cours').count()}")
print(f"Interprété: {Exam.objects.filter(status='Interprété').count()}")

for exam in Exam.objects.filter(status='En cours'):
    print(f"Exam {exam.study_instance_uid} assigned to {exam.assigned_to}")

print("\nSessions:")
for session in CalendarSession.objects.all():
    print(f"Session for {session.doctor.user.email} on {session.date}: {session.count} exams")

