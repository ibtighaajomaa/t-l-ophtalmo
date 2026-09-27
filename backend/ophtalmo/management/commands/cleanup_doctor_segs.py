# -*- coding: utf-8 -*-
"""
Ne garde, dans Orthanc, que la version finale de chaque correction medecin.

Avant l'ajout du remplacement automatique, chaque clic sur "Sauvegarder"
creait une nouvelle serie "Corrige par medecin" ; une etude pouvait en
accumuler plusieurs pour la meme photo. Cette commande regroupe les
corrections par photo source ET par type (lesions, vaisseaux, papille...),
garde la plus recente (date de derniere mise a jour dans Orthanc) et supprime
les autres. Les series de l'IA ne sont jamais concernees.

Simulation par defaut ; --apply pour supprimer.
"""

from django.core.management.base import BaseCommand

import requests


class Command(BaseCommand):
    help = "Supprime les anciennes versions des corrections medecin (DICOM-SEG) dans Orthanc."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Supprime reellement. Sans cette option : simulation.")
        parser.add_argument("--study", dest="study_uid", help="Limiter a ce StudyInstanceUID.")

    def handle(self, *args, **options):
        from ophtalmo.doctor_seg import list_doctor_segs
        from ophtalmo.views import ORTHANC_URL

        apply_changes = options["apply"]
        self.stdout.write(self.style.WARNING(
            "Mode : %s" % ("SUPPRESSION" if apply_changes else "SIMULATION (ajouter --apply pour supprimer)")
        ))

        if options.get("study_uid"):
            study_uids = [options["study_uid"]]
        else:
            response = requests.get("%s/studies" % ORTHANC_URL.rstrip("/"), timeout=30)
            response.raise_for_status()
            study_uids = []
            for study_id in response.json() or []:
                study = requests.get("%s/studies/%s" % (ORTHANC_URL.rstrip("/"), study_id), timeout=30)
                study.raise_for_status()
                uid = (study.json().get("MainDicomTags") or {}).get("StudyInstanceUID")
                if uid:
                    study_uids.append(uid)

        kept = removed = 0
        for study_uid in study_uids:
            segs = list_doctor_segs(ORTHANC_URL, study_uid)
            groups = {}
            for seg in segs:
                key = (tuple(sorted(seg["sources"])), seg["kind"])
                groups.setdefault(key, []).append(seg)
            for (sources, kind), items in groups.items():
                items.sort(key=lambda item: item["last_update"])
                final = items[-1]
                kept += 1
                for old in items[:-1]:
                    removed += 1
                    self.stdout.write(
                        "  etude %s | type %s | photo %s | ancienne %s (%s) -> %s"
                        % (study_uid[-12:], kind, (sources[0][-12:] if sources else "?"),
                           old["series_uid"][-12:], old["last_update"],
                           "supprimee" if apply_changes else "a supprimer")
                    )
                    if apply_changes:
                        response = requests.delete(
                            "%s/series/%s" % (ORTHANC_URL.rstrip("/"), old["orthanc_id"]), timeout=30
                        )
                        response.raise_for_status()
                if len(items) > 1:
                    self.stdout.write(
                        "  etude %s | type %s | version finale gardee : %s (%s)"
                        % (study_uid[-12:], kind, final["series_uid"][-12:], final["last_update"])
                    )

        self.stdout.write(self.style.SUCCESS(
            "Versions finales gardees : %d ; anciennes versions %s : %d"
            % (kept, "supprimees" if apply_changes else "a supprimer", removed)
        ))
