"""Vérifie la connexion au SIIS et, en option, recherche un patient.

    python manage.py siis_check
    python manage.py siis_check --cin 12345678 --birth-date 1990-01-15
    python manage.py siis_check --social-id 3017037173 --birth-date 1839-03-14
    python manage.py siis_check --ins 7061422925
"""
import json

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from ophtalmo import siis_client


class Command(BaseCommand):
    help = "Teste l'authentification au SIIS et la recherche de l'INS d'un patient."

    def add_arguments(self, parser):
        parser.add_argument("--cin")
        parser.add_argument("--social-id")
        parser.add_argument("--ins")
        parser.add_argument("--birth-date", help="AAAA-MM-JJ, avec --cin ou --social-id")

    def handle(self, *args, **opts):
        self.stdout.write(f"SIIS : {settings.SIIS_BASE_URL} (compte « {settings.SIIS_USERNAME or '—'} »)")
        cache.delete(siis_client.ACCESS_TOKEN_KEY)
        cache.delete(siis_client.LOGIN_BLOCKED_KEY)
        try:
            siis_client._access_token()
        except siis_client.SIISError as exc:
            raise CommandError(f"Authentification impossible : {exc}")
        self.stdout.write(self.style.SUCCESS("Authentification réussie."))

        if opts["ins"]:
            criteria = {"ids": opts["ins"]}
        elif opts["cin"] or opts["social_id"]:
            if not opts["birth_date"]:
                raise CommandError("--birth-date est obligatoire avec --cin ou --social-id.")
            key, value = ("cin", opts["cin"]) if opts["cin"] else ("socialId", opts["social_id"])
            criteria = {key: value, "birthDate": opts["birth_date"]}
        else:
            return
        try:
            patients = siis_client.search_patients(criteria)
        except siis_client.SIISError as exc:
            raise CommandError(f"Recherche en échec : {exc}")
        self.stdout.write(json.dumps(patients, ensure_ascii=False, indent=2))
