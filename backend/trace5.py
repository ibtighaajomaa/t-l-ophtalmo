import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth.models import User
from ophtalmo.models import Exam, CalendarSession
from datetime import date, datetime
from django.db.models import Count
from django.utils import timezone

date_str = '2026-06-29'
session_date = datetime.strptime(date_str, '%Y-%m-%d').date()
a_assigner = 1

actual_assigned = 0
now = timezone.now()
today = timezone.localdate()

print("session_date:", session_date)
print("today:", today)
print("session_date == today:", session_date == today)

if session_date == today:
    region_counts_qs = Exam.objects.filter(status='En cours').values('region').annotate(count=Count('id'))
    region_counts = {item['region']: item['count'] for item in region_counts_qs if item['region']}
    
    exams_attente = list(Exam.objects.filter(status='En attente', assigned_to__isnull=True))
    print("len(exams_attente):", len(exams_attente))
    
    if exams_attente:
        def sort_key(exam):
            prio = 0 if exam.priority == 'Urgent' else 1
            age = exam.date.toordinal() if exam.date else 0
            region_count = region_counts.get(exam.region, 0)
            return (prio, age, region_count, exam.id)
            
        exams_attente.sort(key=sort_key)
        
        exams_to_assign = exams_attente[:a_assigner]
        actual_assigned = len(exams_to_assign)
        print("actual_assigned:", actual_assigned)

msg = f'{actual_assigned} examens assignés au Dr Test.'
if actual_assigned < a_assigner:
    msg += f' (Il ne restait que {actual_assigned} examens disponibles sur les {a_assigner} demandés).'

print("MSG:", msg)
