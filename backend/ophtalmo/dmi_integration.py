import logging

from django.conf import settings
from django.db import transaction

from .models import DMIAuditLog, Exam

logger = logging.getLogger(__name__)


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "oui", "o", "yes", "y"}


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _status_from_dmi(value):
    normalized = _clean(value).lower()
    if normalized in {"interprété", "interprete", "terminé", "termine"}:
        return Exam.Status.INTERPRETE
    if normalized in {"en cours", "encours"}:
        return Exam.Status.EN_COURS
    return Exam.Status.EN_ATTENTE


def _clinical_summary(clinical_info):
    if not clinical_info:
        return ""
    rows = [
        ("Type de diabète", clinical_info.get("diabete_type")),
        ("Durée du diabète", clinical_info.get("duree_diabete")),
        (
            "Dernière glycémie",
            " ".join(
                part for part in [
                    _clean(clinical_info.get("derniere_glycemie")),
                    f"le {_clean(clinical_info.get('date_derniere_glycemie'))}" if clinical_info.get("date_derniere_glycemie") else "",
                ] if part
            ),
        ),
        (
            "Dernière HbA1c",
            " ".join(
                part for part in [
                    _clean(clinical_info.get("derniere_hba1c")),
                    f"le {_clean(clinical_info.get('date_derniere_hba1c'))}" if clinical_info.get("date_derniere_hba1c") else "",
                ] if part
            ),
        ),
        ("Traitement", clinical_info.get("type_traitement")),
        ("HTA", "Oui" if _truthy(clinical_info.get("hta")) else "Non"),
        ("Autre pathologie", clinical_info.get("autre_pathologie")),
        ("Motif et notes", clinical_info.get("motif_notes")),
    ]
    return "\n".join(f"{label}: {_clean(value)}" for label, value in rows if _clean(value))


def upsert_exam_from_dmi(payload):
    numero_examen = _clean(payload.get("numero_examen") or payload.get("dmi_exam_id"))
    if not numero_examen:
        raise ValueError("numero_examen est obligatoire")

    date_examen = payload.get("date_examen")
    if not date_examen:
        raise ValueError("date_examen est obligatoire")

    clinical_info = payload.get("clinical_info") or {}
    defaults = {
        "patient_id": _clean(payload.get("ipp") or payload.get("patient_id")),
        "patient_name": _clean(payload.get("patient_name")) or f"Patient DMI {numero_examen}",
        "date": date_examen,
        "status": _status_from_dmi(payload.get("etat")),
        "priority": Exam.Priority.URGENT if _truthy(payload.get("urgent")) else Exam.Priority.NORMAL,
        "exam_type": payload.get("exam_type") or Exam.ExamType.RETINOGRAPHIE,
        "dmi_service_code": _clean(payload.get("service_code")),
        "dmi_service_name": _clean(payload.get("service_name")),
        "dmi_provenance": _clean(payload.get("provenance")),
        "dmi_matricule": _clean(payload.get("matricule")),
        "dmi_date_episode": payload.get("date_episode") or None,
        "dmi_medecin_referent_code": _clean(payload.get("medecin_code")),
        "dmi_medecin_referent_nom": _clean(payload.get("medecin_nom")),
        "dmi_code_ccam": _clean(payload.get("code_ccam")),
        "clinical_info": clinical_info or None,
        "patient_history": _clinical_summary(clinical_info),
    }

    with transaction.atomic():
        exam, created = Exam.objects.update_or_create(
            dmi_exam_id=numero_examen,
            defaults=defaults,
        )
    return exam, created


def is_valid_dmi_request(request):
    expected_token = getattr(settings, "DMI_API_TOKEN", "")
    if not expected_token:
        return False
    received_token = request.META.get("HTTP_X_DMI_SERVICE_TOKEN", "")
    return received_token == expected_token


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def audit_dmi_call(request, numero_examen="", success=False, status_code=0, error_message=""):
    try:
        DMIAuditLog.objects.create(
            endpoint=request.path[:255],
            method=request.method,
            caller_ip=_client_ip(request)[:64],
            numero_examen=_clean(numero_examen),
            success=success,
            status_code=status_code,
            error_message=_clean(error_message)[:2000],
        )
    except Exception:
        logger.exception("Impossible d'enregistrer l'audit DMI")


def build_dicom_acquisition_payload(exam):
    results = list(exam.image_quality_results.all())
    label_map = {
        "good": "Bonne",
        "acceptable": "Acceptable",
        "bad": "Mauvaise",
    }
    return {
        "numero_examen": exam.dmi_exam_id,
        "date_examen": exam.date.isoformat() if exam.date else None,
        "nb_images": len(results),
        "quality_status": exam.quality_status,
        "quality_score": exam.quality_score,
        "quality_category": exam.quality_category,
        "quality_label": label_map.get(exam.quality_category, exam.quality_category),
        "instances": [
            {
                "index": index,
                "sop_instance_uid": result.sop_instance_uid,
                "score": result.score,
                "score_display": f"{result.score:.1f}/100",
                "category": result.category,
                "label": label_map.get(result.category, result.category),
            }
            for index, result in enumerate(results, start=1)
        ],
    }


def _doctor_payload(user):
    if not user:
        return {}
    profil = getattr(user, "profil", None)
    return {
        "id": user.id,
        "username": user.username,
        "nom": f"{user.first_name} {user.last_name}".strip() or user.username,
        "email": user.email,
        "matricule": getattr(profil, "matricule", "") if profil else "",
        "contact": getattr(profil, "telephone", "") if profil else "",
    }


def build_compte_rendu_payload(exam, report):
    doctor = exam.assigned_to or report.signed_by or report.validated_by
    return {
        "numero_examen": exam.dmi_exam_id,
        "ipp": report.patient_id or exam.patient_id,
        "code_ccam": exam.dmi_code_ccam,
        "statut": Exam.Status.INTERPRETE,
        "compte_rendu": report.final_content or report.doctor_content or report.ai_content,
        "date_validation": report.signed_at.isoformat() if report.signed_at else None,
        "medecin_traitant": _doctor_payload(doctor),
    }
