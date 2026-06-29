import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from ophtalmo.distribution import get_examens_en_attente, get_medecins_disponibles, trier_avec_equite_regionale
from ophtalmo.models import CalendarSession
from django.utils import timezone

examens_attente = list(get_examens_en_attente())
medecins = list(get_medecins_disponibles())

examens_tries = trier_avec_equite_regionale(examens_attente)
distribues = 0

today = timezone.localdate()
sessions_aujourdhui = CalendarSession.objects.filter(date=today)
session_map = {}
for s in sessions_aujourdhui:
    session_map[s.doctor_id] = session_map.get(s.doctor_id, 0) + s.count
print("session_map", session_map)

medecins_prioritaires = []
for med in medecins:
    demande = session_map.get(med.user_id, 0)
    print("med:", med, "demande:", demande, "charge:", med.charge_actuelle)
    if demande > med.charge_actuelle:
        medecins_prioritaires.append(med)
print("medecins_prioritaires before loop:", medecins_prioritaires)

if medecins_prioritaires:
    med_idx = 0
    while examens_tries and medecins_prioritaires:
        medecin = medecins_prioritaires[med_idx % len(medecins_prioritaires)]
        demande = session_map.get(medecin.user_id, 0)
        
        print("evaluating med:", medecin, "demande:", demande, "charge:", medecin.charge_actuelle)
        if medecin.charge_actuelle < demande:
            examen = examens_tries.pop(0)
            print("assigned exam:", examen)
            # We don't save to db, just trace
            medecin.charge_actuelle += 1
            distribues += 1
            med_idx += 1
        else:
            medecins_prioritaires.remove(medecin)

print("distribues:", distribues)
