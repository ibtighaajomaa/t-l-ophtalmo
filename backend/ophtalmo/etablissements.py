"""
Rapprochement entre le nom d'établissement rattaché à un utilisateur
(ex. "HOPITAL REGIONAL KEBILI") et les libellés réellement stockés sur les
examens / modalités (ex. "kebili", "Hôpital de Kélibia", "Manzel Temim").

Les libellés viennent de sources différentes (liste déroulante du front,
table DicomModalitySite, tag DICOM InstitutionName), d'où une comparaison
tolérante : accents ignorés, mots génériques ignorés, préfixes acceptés.
"""
import re
import unicodedata

from django.db.models import Q

# Mots trop génériques pour identifier un établissement.
_STOPWORDS = {
    "hopital", "hospital", "hop", "hc", "hr", "chu", "centre", "center",
    "regional", "circonscription", "local", "universitaire", "de", "du",
    "des", "la", "le", "les", "el", "al", "d", "l",
}


def normalize(value):
    """Minuscules, sans accents, sans ponctuation."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def keywords(value):
    """Mots discriminants d'un libellé d'établissement."""
    return {w for w in normalize(value).split() if len(w) >= 3 and w not in _STOPWORDS}


def _tokens_match(a, b):
    if a == b:
        return True
    # "temim" / "temime", "kelibia" / "kelibiaa" : préfixe d'au moins 4 lettres.
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter)


def etablissement_matches(etablissement, candidate):
    """True si les deux libellés désignent vraisemblablement le même site."""
    if not etablissement or not candidate:
        return False
    if normalize(etablissement) == normalize(candidate):
        return True
    kw_a, kw_b = keywords(etablissement), keywords(candidate)
    if not kw_a or not kw_b:
        return False
    return any(_tokens_match(a, b) for a in kw_a for b in kw_b)


def filter_exams_by_etablissement(exams, etablissement):
    """
    Restreint un queryset d'examens à ceux d'un établissement donné.
    Sans établissement, ou sans correspondance, le queryset est vide :
    un technicien ne doit jamais voir les examens d'un autre site.
    """
    from .models import DicomModalitySite

    if not etablissement:
        return exams.none()

    matching_ips = [
        ip for name, ip in DicomModalitySite.objects.values_list("institution_name", "remote_ip")
        if ip and etablissement_matches(etablissement, name)
    ]
    matching_regions = [
        region for region in exams.model.objects.exclude(region="")
        .values_list("region", flat=True).distinct()
        if etablissement_matches(etablissement, region)
    ]
    if not matching_ips and not matching_regions:
        return exams.none()
    return exams.filter(Q(region__in=matching_regions) | Q(modality_ip__in=matching_ips))
