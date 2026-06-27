import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from ophtalmo.models import Exam

unassigned_exams = Exam.objects.filter(assigned_to__isnull=True)
statuses = set(unassigned_exams.values_list('status', flat=True))
print(f"Distinct statuses for unassigned exams: {statuses}")

# Print 5 unassigned exams
for e in unassigned_exams[:5]:
    print(f"ID={e.id}, status='{e.status}'")

# Force update all unassigned exams to 'En attente'
count = Exam.objects.filter(assigned_to__isnull=True).exclude(status='En attente').update(status='En attente')
print(f"Force updated {count} exams to 'En attente'")
