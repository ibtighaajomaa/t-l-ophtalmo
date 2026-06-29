import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from ophtalmo.distribution import get_medecins_disponibles, get_examens_en_attente, trier_avec_equite_regionale
from ophtalmo.models import CalendarSession, Exam
from django.utils import timezone

medecins = list(get_medecins_disponibles())
print("medecins:", medecins)

examens_attente = list(get_examens_en_attente())
examens_tries = trier_avec_equite_regionale(examens_attente)
print("examens_tries:", examens_tries)

today = timezone.localdate()
print("today:", today)
sessions_aujourdhui = CalendarSession.objects.filter(date=today)
print("sessions_aujourdhui:", sessions_aujourdhui)

session_map = {}
for s in sessions_aujourdhui:
    session_map[s.doctor_id] = session_map.get(s.doctor_id, 0) + s.count
print("session_map:", session_map)

medecins_prioritaires = []
for med in medecins:
    demande = session_map.get(med.user_id, 0)
    if demande > med.charge_actuelle:
        medecins_prioritaires.append(med)
print("medecins_prioritaires:", medecins_prioritaires)
