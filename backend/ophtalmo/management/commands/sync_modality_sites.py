# -*- coding: utf-8 -*-
"""
Synchronise la table DicomModalitySite et normalise le nom d'etablissement
stocke sur les examens.

Deux problemes sont traites ici :

1. Un meme etablissement existe sous plusieurs orthographes ("kelibia",
   "Hopital de Kelibia", "HOPITAL CIRCONSCRITION KELIBIA"), ce qui le compte
   comme plusieurs sites distincts sur la carte et dans les statistiques.

2. Le rapprochement par adresse IP ne survit pas au NAT : une camera derriere
   une passerelle est vue avec l'IP publique de l'hopital, pas son IP privee.
   Les IP privees ne sont pas non plus uniques entre hopitaux. On ajoute donc
   des lignes indexees sur l'AE title, qui voyage dans l'association DICOM et
   n'est jamais reecrit.

Les noms canoniques choisis ici correspondent tous a une cle existante de
SITE_LOCATIONS cote frontend (apres normalisation : accents retires, minuscules).
Ne pas les changer sans ajouter la cle correspondante dans _app.analyse.tsx,
sinon le site disparait de la carte nationale.
"""

import unicodedata

from django.core.management.base import BaseCommand
from django.db import transaction


# (remote_ip, remote_aet, institution_name)
MODALITY_SITES = [
    ("192.168.149.10", "", "Menzel Temim"),
    ("192.168.149.6", "", "Menzel Temim"),
    ("192.168.167.116", "Canon RC Capture", "Kélibia"),
    ("192.168.167.117", "RETINO_KELIBIA", "Kélibia"),
    ("172.22.12.232", "", "Kébili"),
    ("192.168.254.44", "", "Deguech"),
    ("172.22.158.100", "", "Mateur"),
    ("192.172.35.37", "", "Siliana"),

    # Lignes AE title seules : resistent au NAT, contrairement aux IP privees.
    # Ajouter ici l'AE title reel de chaque retinographe au fur et a mesure.
    ("", "Canon RC Capture", "Kélibia"),
    ("", "RETINO_KELIBIA", "Kélibia"),
]

# Variantes rencontrees -> nom canonique.
ALIASES = {
    "manzel temim": "Menzel Temim",
    "menzel temim": "Menzel Temim",
    "menzel temime": "Menzel Temim",
    "manzel tmim": "Menzel Temim",
    "kelibia": "Kélibia",
    "hopital de kelibia": "Kélibia",
    "hopital circonscrition kelibia": "Kélibia",
    "hopital circonscription kelibia": "Kélibia",
    "kebili": "Kébili",
    "deguech": "Deguech",
    "degueche": "Deguech",
    "mateur": "Mateur",
    "siliana": "Siliana",
}


def normalize(value):
    """Meme normalisation que normalizeSiteName() cote frontend."""
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    cleaned = []
    for char in text:
        cleaned.append(char if (char.isalnum() or char == "_" or char.isspace()) else " ")
    return " ".join("".join(cleaned).split()).strip().lower()


def canonical_name(value):
    """Renvoie le nom canonique, ou la valeur d'origine si elle est inconnue."""
    return ALIASES.get(normalize(value), value)


class Command(BaseCommand):
    help = "Synchronise les mappings modalite -> etablissement et normalise Exam.region."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Ecrit reellement. Sans cette option, simulation seule.",
        )
        parser.add_argument(
            "--backfill",
            action="store_true",
            help="Normalise aussi Exam.region sur les examens deja enregistres.",
        )

    def handle(self, *args, **options):
        from ophtalmo.models import DicomModalitySite, Exam

        apply_changes = options["apply"]
        mode = "APPLICATION" if apply_changes else "SIMULATION (ajouter --apply pour ecrire)"
        self.stdout.write(self.style.WARNING("Mode : %s" % mode))

        created = updated = unchanged = 0

        with transaction.atomic():
            for remote_ip, remote_aet, institution in MODALITY_SITES:
                row = DicomModalitySite.objects.filter(
                    remote_ip=remote_ip, remote_aet=remote_aet
                ).first()

                if row is None:
                    created += 1
                    self.stdout.write(
                        "  + %-16s %-18s -> %s"
                        % (remote_ip or "-", remote_aet or "-", institution)
                    )
                    if apply_changes:
                        DicomModalitySite.objects.create(
                            remote_ip=remote_ip,
                            remote_aet=remote_aet,
                            institution_name=institution,
                            is_active=True,
                        )
                elif row.institution_name != institution or not row.is_active:
                    updated += 1
                    self.stdout.write(
                        "  ~ %-16s %-18s : %s -> %s%s"
                        % (
                            remote_ip or "-",
                            remote_aet or "-",
                            row.institution_name,
                            institution,
                            "" if row.is_active else " (reactive)",
                        )
                    )
                    if apply_changes:
                        row.institution_name = institution
                        row.is_active = True
                        row.save(update_fields=["institution_name", "is_active", "updated_at"])
                else:
                    unchanged += 1

            # Normalise aussi les lignes ajoutees a la main depuis l'admin Django.
            for row in DicomModalitySite.objects.all():
                target = canonical_name(row.institution_name)
                if target != row.institution_name:
                    updated += 1
                    self.stdout.write(
                        "  ~ %-16s %-18s : %s -> %s"
                        % (
                            row.remote_ip or "-",
                            row.remote_aet or "-",
                            row.institution_name,
                            target,
                        )
                    )
                    if apply_changes:
                        row.institution_name = target
                        row.save(update_fields=["institution_name", "updated_at"])

            self.stdout.write(
                self.style.SUCCESS(
                    "Mappings : %d cree(s), %d modifie(s), %d inchange(s)."
                    % (created, updated, unchanged)
                )
            )

            if options["backfill"]:
                self._backfill(Exam, DicomModalitySite, apply_changes)

            if not apply_changes:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Simulation : aucune ecriture conservee."))

    def _backfill(self, Exam, DicomModalitySite, apply_changes):
        by_ip = {
            row.remote_ip: row.institution_name
            for row in DicomModalitySite.objects.filter(is_active=True).exclude(remote_ip="")
        }

        renamed = resolved = 0
        for exam in Exam.objects.all().only("id", "region", "modality_ip"):
            target = canonical_name(exam.region)

            # Region vide ou inconnue : tenter l'IP de la modalite emettrice.
            if normalize(target) in ("", "etablissement inconnu"):
                mapped = by_ip.get(exam.modality_ip or "")
                if mapped:
                    target = mapped
                    resolved += 1

            if target != exam.region:
                renamed += 1
                self.stdout.write("  exam %s : %r -> %r" % (exam.id, exam.region, target))
                if apply_changes:
                    exam.region = target
                    exam.save(update_fields=["region", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                "Examens : %d mis a jour (dont %d resolus via l'IP de la modalite)."
                % (renamed, resolved)
            )
        )
