"""Rattachement des patients adressés par un médecin référant aux examens."""
from django.db import transaction

from .dmi_integration import _clinical_summary
from .models import Exam, PatientReferral


def build_history(clinical_info, free_text=""):
    parts = [_clinical_summary(clinical_info or {}), (free_text or "").strip()]
    return "\n".join(part for part in parts if part)


def apply_referral(exam, referral, save=True):
    """Reporte priorité, âge et antécédents du patient adressé sur l'examen."""
    changed = []
    if exam.priority != referral.priority:
        exam.priority = referral.priority
        changed.append("priority")
    if exam.patient_age is None and referral.patient_age is not None:
        exam.patient_age = referral.patient_age
        changed.append("patient_age")
    if referral.clinical_info and exam.clinical_info != referral.clinical_info:
        exam.clinical_info = referral.clinical_info
        changed.append("clinical_info")
    if referral.patient_history and exam.patient_history != referral.patient_history:
        exam.patient_history = referral.patient_history
        changed.append("patient_history")
    if save and changed:
        exam.save(update_fields=changed + ["updated_at"])
    return changed


def link_exam_to_pending_referral(exam):
    """Appelé à la création d'un examen : rattache le dernier patient adressé non lié."""
    patient_id = (exam.patient_id or "").strip()
    if not patient_id:
        return None
    with transaction.atomic():
        referral = (
            PatientReferral.objects.select_for_update()
            .filter(patient_id__iexact=patient_id, exam__isnull=True)
            .order_by("-created_at", "-id")
            .first()
        )
        if referral is None:
            return None
        apply_referral(exam, referral)
        referral.exam = exam
        referral.save(update_fields=["exam"])
    return referral


def link_referral_to_existing_exam(referral):
    """Appelé à la saisie : rattache l'examen non interprété le plus récent du patient."""
    exam = (
        Exam.objects.filter(patient_id__iexact=referral.patient_id, referral__isnull=True)
        .exclude(status=Exam.Status.INTERPRETE)
        .order_by("-date", "-id")
        .first()
    )
    if exam is None:
        return None
    apply_referral(exam, referral)
    referral.exam = exam
    referral.save(update_fields=["exam"])
    return exam
