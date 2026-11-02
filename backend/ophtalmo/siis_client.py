"""Client du SIIS (Ministère de la Santé) : recherche de l'INS d'un citoyen.

Contrat « Exposition et Consommation des APIs de SIIS » :

- ``POST {SIIS_BASE_URL}/api/v1/auth/login`` ``{username, password}`` puis
  ``/api/v1/auth/refresh`` ``{refreshToken}`` : réponse ``OperationOutcome`` dont
  les extensions portent ``accessToken``, ``refreshToken`` et ``expiresIn`` ;
- ``POST {SIIS_BASE_URL}/api/v1/fhir/Patient/_search`` (Bearer) : ``Bundle`` FHIR
  de ressources ``Patient`` dont les extensions portent l'INS (``ids``), les noms
  en français et en arabe, l'identifiant social, etc.

Seules les recherches sans effet de bord sont utilisées : CIN + date de
naissance, identifiant social + date de naissance, ou INS seul. La recherche
par données biographiques peut créer le citoyen dans le registre national ;
elle n'est pas exposée ici.
"""
import base64
import json
import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

ACCESS_TOKEN_KEY = "siis:access_token"
REFRESH_TOKEN_KEY = "siis:refresh_token"
# Le SIIS bloque le compte après 10 échecs de connexion : on suspend les
# tentatives après un refus pour ne pas verrouiller le compte partagé.
LOGIN_BLOCKED_KEY = "siis:login_blocked"
LOGIN_BLOCK_SECONDS = 300


class SIISError(Exception):
    """Erreur SIIS ; ``status`` est le code HTTP à renvoyer au navigateur."""

    status = 502

    def __init__(self, message, status=None):
        super().__init__(message)
        if status is not None:
            self.status = status


class SIISNotConfigured(SIISError):
    status = 503


class SIISUnavailable(SIISError):
    status = 503


class SIISNotFound(SIISError):
    status = 404


class SIISInvalidRequest(SIISError):
    status = 400


def is_configured():
    return bool(settings.SIIS_BASE_URL and settings.SIIS_USERNAME and settings.SIIS_PASSWORD)


def _url(path):
    return f"{settings.SIIS_BASE_URL}{path}"


def _post(path, payload, token=None):
    headers = {"Accept": "application/fhir+json, application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return requests.post(
            _url(path),
            json=payload,
            headers=headers,
            # Connexion courte : un SIIS injoignable ne doit pas bloquer l'écran du médecin.
            timeout=(min(5.0, settings.SIIS_TIMEOUT), settings.SIIS_TIMEOUT),
            verify=settings.SIIS_VERIFY_SSL,
        )
    except requests.RequestException as exc:
        logger.warning("SIIS injoignable (%s) : %s", path, exc)
        raise SIISUnavailable("Le SIIS est injoignable. Réessayez dans quelques instants.") from exc


def _json(response):
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _extension_key(url):
    """``…/StructureDefinition/firstNameFR.json`` → ``firstnamefr``."""
    last = str(url or "").rstrip("/").rsplit("/", 1)[-1]
    if last.endswith(".json"):
        last = last[: -len(".json")]
    return last.lower()


def _extensions(resource):
    values = {}
    for ext in resource.get("extension") or []:
        if not isinstance(ext, dict):
            continue
        value = next((ext[k] for k in ext if k.startswith("value")), None)
        values[_extension_key(ext.get("url"))] = value
    return values


def _issue_text(body):
    """Texte lisible d'un ``OperationOutcome`` (diagnostics ou details.text)."""
    for issue in body.get("issue") or []:
        if not isinstance(issue, dict):
            continue
        text = (issue.get("details") or {}).get("text") or issue.get("diagnostics")
        if text:
            return str(text)
    return ""


def _issue_codes(body):
    return {str(i.get("code") or "") for i in body.get("issue") or [] if isinstance(i, dict)}


def _jwt_exp(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return float(exp) if exp else None
    except Exception:
        return None


def _ttl(token, expires_in=None, default=600):
    """Durée de cache d'un jeton, avec une marge d'une minute.

    L'``exp`` du JWT fait foi ; à défaut, ``expiresIn`` (900000 dans le contrat,
    donc en millisecondes au-delà d'une journée).
    """
    exp = _jwt_exp(token)
    if exp:
        seconds = exp - time.time()
    elif expires_in:
        seconds = float(expires_in)
        if seconds > 86400:
            seconds /= 1000
    else:
        seconds = default
    return max(int(seconds) - 60, 0)


def _store_tokens(body):
    ext = _extensions(body)
    access = ext.get("accesstoken")
    if not access:
        raise SIISError("Réponse d'authentification SIIS sans jeton d'accès.")
    ttl = _ttl(access, ext.get("expiresin"))
    if ttl:
        cache.set(ACCESS_TOKEN_KEY, access, ttl)
    refresh = ext.get("refreshtoken")
    if refresh:
        cache.set(REFRESH_TOKEN_KEY, refresh, _ttl(refresh, default=86400) or None)
    return access


def _login():
    if not is_configured():
        raise SIISNotConfigured("Le connecteur SIIS n'est pas configuré (SIIS_USERNAME / SIIS_PASSWORD).")
    if cache.get(LOGIN_BLOCKED_KEY):
        raise SIISUnavailable(
            "Connexion au SIIS suspendue après un refus d'authentification. Réessayez dans quelques minutes."
        )
    res = _post("/api/v1/auth/login", {"username": settings.SIIS_USERNAME, "password": settings.SIIS_PASSWORD})
    if res.status_code == 200:
        return _store_tokens(_json(res))
    detail = _issue_text(_json(res)) or f"HTTP {res.status_code}"
    logger.error("Authentification SIIS refusée : %s", detail)
    if res.status_code in (401, 403, 429):
        cache.set(LOGIN_BLOCKED_KEY, True, LOGIN_BLOCK_SECONDS)
        raise SIISError("Authentification au SIIS refusée. Contactez l'administrateur de la plateforme.")
    raise SIISUnavailable("Le SIIS ne répond pas correctement. Réessayez dans quelques instants.")


def _refresh():
    refresh = cache.get(REFRESH_TOKEN_KEY)
    if not refresh:
        return None
    try:
        res = _post("/api/v1/auth/refresh", {"refreshToken": refresh})
    except SIISUnavailable:
        return None
    if res.status_code != 200:
        cache.delete(REFRESH_TOKEN_KEY)
        return None
    try:
        return _store_tokens(_json(res))
    except SIISError:
        return None


def _access_token(renew=False):
    if renew:
        cache.delete(ACCESS_TOKEN_KEY)
    else:
        token = cache.get(ACCESS_TOKEN_KEY)
        if token:
            return token
    return _refresh() or _login()


GENDERS = {"male": "M", "female": "F", "other": "O"}


def _patient(resource):
    """Ressource FHIR ``Patient`` du SIIS → dictionnaire plat pour l'API interne."""
    ext = _extensions(resource)

    def text(*keys):
        for key in keys:
            value = ext.get(key.lower())
            if value not in (None, ""):
                return str(value).strip()
        return ""

    ins = text("ids")
    if not ins:
        for identifier in resource.get("identifier") or []:
            if isinstance(identifier, dict) and identifier.get("value"):
                ins = str(identifier["value"]).strip()
                break
    deceased = resource.get("deceasedBoolean")
    return {
        "ins": ins,
        "first_name_fr": text("firstNameFR"),
        "last_name_fr": text("lastNameFR"),
        "first_name_ar": text("firstNameAR"),
        "last_name_ar": text("lastNameAR"),
        "filiation_fr": text("fatherFirstNameFR", "grandFatherFirstNameFR"),
        "filiation_ar": text("fatherFirstNameAR", "grandFatherFirstNameAR"),
        "gender": GENDERS.get(str(resource.get("gender") or "").lower(), ""),
        "birth_date": str(resource.get("birthDate") or "")[:10],
        "deceased": bool(deceased) or bool(resource.get("deceasedDateTime")),
    }


def _patients(body):
    if body.get("resourceType") == "Patient":
        resources = [body]
    else:
        resources = [
            entry.get("resource")
            for entry in body.get("entry") or []
            if isinstance(entry, dict) and isinstance(entry.get("resource"), dict)
        ]
    patients = [_patient(r) for r in resources if r.get("resourceType", "Patient") == "Patient"]
    return [p for p in patients if p["ins"]]


def search_patients(criteria):
    """Recherche un citoyen dans le SIIS ; renvoie au moins un patient doté d'un INS.

    ``criteria`` suit le contrat : ``{"cin", "birthDate"}``, ``{"socialId",
    "birthDate"}`` ou ``{"ids"}``. Lève ``SIISNotFound`` si personne ne correspond.
    """
    for attempt in range(2):
        res = _post("/api/v1/fhir/Patient/_search", criteria, token=_access_token(renew=attempt > 0))
        if res.status_code == 401 and attempt == 0:
            continue
        break

    body = _json(res)
    if res.status_code == 200:
        patients = _patients(body)
        if not patients:
            raise SIISNotFound("Aucun citoyen ne correspond à ces critères dans le SIIS.")
        return patients
    detail = _issue_text(body)
    if res.status_code == 404 or "not-found" in _issue_codes(body):
        raise SIISNotFound("Aucun citoyen ne correspond à ces critères dans le SIIS.")
    if res.status_code in (400, 422):
        raise SIISInvalidRequest(f"Recherche refusée par le SIIS : {detail or 'critères invalides'}.")
    if res.status_code == 401:
        raise SIISError("Le SIIS refuse le jeton d'accès de la plateforme.")
    if res.status_code == 429:
        raise SIISUnavailable("Trop de recherches simultanées vers le SIIS. Réessayez dans une minute.")
    logger.error("Recherche SIIS en échec (HTTP %s) : %s", res.status_code, detail)
    raise SIISUnavailable("Le SIIS ne répond pas correctement. Réessayez dans quelques instants.")


def find_by_ins(ins):
    """Patient du SIIS dont l'INS est exactement ``ins`` (``SIISNotFound`` sinon)."""
    for patient in search_patients({"ids": ins}):
        if patient["ins"] == ins:
            return patient
    raise SIISNotFound("Cet INS est inconnu du SIIS.")
