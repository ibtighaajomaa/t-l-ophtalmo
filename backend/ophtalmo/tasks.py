"""
Tâches Celery pour le système de distribution des examens.
- tache_distribution : distribution immédiate (appelée à chaque nouvel examen)
- tache_verification_24h : vérification périodique des examens en retard (toutes les 24h)
- tache_recalcul_charges : recalcul de sécurité des charges médecins
- tache_sync_orthanc_incremental : synchronisation incrémentale depuis Orthanc (toutes les 60s)
- tache_auto_segmentation : segmentation automatique des nouvelles études OP par MONAI Label
"""
import os
import logging
from datetime import date
import requests
from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)

ORTHANC_URL = os.environ.get('ORTHANC_URL', 'http://orthanc-container:8042')


@shared_task(name='ophtalmo.tasks.tache_distribution')
def tache_distribution():
    """
    Tâche de distribution immédiate.
    Appelée à chaque nouvel examen reçu ou manuellement.
    """
    from .distribution import distribuer_examens
    logger.info("=== Lancement de la distribution des examens ===")
    result = distribuer_examens()
    logger.info(f"=== Distribution terminée : {result} ===")
    return result


@shared_task(name='ophtalmo.tasks.tache_verification_24h')
def tache_verification_24h():
    """
    Tâche périodique (toutes les 24h via Celery Beat).
    1. Vérifie les examens non traités depuis plus de 24h
    2. Réassigne si le médecin n'est plus disponible
    3. Envoie des rappels sinon
    4. Lance une nouvelle distribution
    """
    from .distribution import reassigner_examens_en_retard, distribuer_examens, recalculer_charges

    logger.info("=== Vérification quotidienne des examens ===")

    # 1. Recalculer les charges pour corriger les dérives
    recalcul = recalculer_charges()
    logger.info(f"Recalcul charges : {recalcul}")

    # 2. Réassigner les examens en retard
    reassign = reassigner_examens_en_retard()
    logger.info(f"Réassignation : {reassign}")

    # 3. Nouvelle distribution
    distrib = distribuer_examens()
    logger.info(f"Distribution : {distrib}")

    return {
        'recalcul': recalcul,
        'reassignation': reassign,
        'distribution': distrib,
    }


@shared_task(name='ophtalmo.tasks.tache_recalcul_charges')
def tache_recalcul_charges():
    """Recalcule les charges de tous les médecins (tâche de maintenance)."""
    from .distribution import recalculer_charges
    return recalculer_charges()


@shared_task(name='ophtalmo.tasks.tache_sync_orthanc_incremental')
def tache_sync_orthanc_incremental():
    """
    Synchronisation incrémentale depuis Orthanc (toutes les 60s via Celery Beat).
    Interroge le endpoint /changes d'Orthanc depuis le dernier séquenceur connu
    et crée les examens manquants dans la worklist.
    Complète le Lua webhook OnStableStudy en cas d'échec ou de redémarrage.
    """
    from .models import Exam, AnalysisReport

    last_seq = cache.get('orthanc_changes_seq', 0)

    try:
        resp = requests.get(
            f'{ORTHANC_URL}/changes',
            params={'since': last_seq, 'limit': 100},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"[OrthancSync] Cannot reach Orthanc: {e}")
        return {'status': 'error', 'message': str(e)}

    changes = data.get('Changes', [])
    if not changes:
        return {'status': 'ok', 'processed': 0}

    created = 0
    deleted = 0
    skipped = 0
    new_seq = last_seq

    for change in changes:
        seq = change.get('Seq', 0)
        new_seq = max(new_seq, seq)

        change_type = change.get('ChangeType')

        if change_type == 'DeletedStudy':
            study_id = change.get('ID')
            if study_id:
                AnalysisReport.objects.filter(series_instance_uid=study_id).delete()
                Exam.objects.filter(study_instance_uid=study_id).delete()
                deleted += 1
            continue

        if change_type != 'NewStudy':
            continue

        study_id = change.get('ID')
        if not study_id:
            continue

        if Exam.objects.filter(study_instance_uid=study_id).exists():
            skipped += 1
            continue

        try:
            detail = requests.get(f'{ORTHANC_URL}/studies/{study_id}', timeout=15)
            detail.raise_for_status()
            meta = detail.json()
        except requests.RequestException:
            skipped += 1
            continue

        main_patient = meta.get('PatientMainDicomTags', {})
        patient_name = main_patient.get('PatientName', 'Unknown')
        patient_age = None
        age_str = main_patient.get('PatientAge', '')
        if age_str and age_str.rstrip('Y').isdigit():
            patient_age = int(age_str.rstrip('Y'))

        study_date_str = meta.get('MainDicomTags', {}).get('StudyDate', '')
        study_date = date.today()
        if study_date_str and len(study_date_str) == 8:
            try:
                study_date = date(
                    int(study_date_str[:4]),
                    int(study_date_str[4:6]),
                    int(study_date_str[6:8]),
                )
            except ValueError:
                pass

        main_dicom = meta.get('MainDicomTags', {})
        institution = main_dicom.get('InstitutionName', '')
        region = institution if institution else ''

        Exam.objects.create(
            study_instance_uid=study_id,
            patient_name=patient_name,
            patient_age=patient_age,
            exam_type='Rétinographie',
            date=study_date,
            priority='Normal',
            status='En attente',
            region=region,
            modality_ip='',
            notes='',
        )
        created += 1

    cache.set('orthanc_changes_seq', new_seq, timeout=None)

    if created > 0:
        try:
            tache_distribution.delay()
        except Exception:
            from .distribution import distribuer_examens
            distribuer_examens()

    if created > 0:
        # Déclencher la segmentation automatique pour les nouvelles études
        tache_auto_segmentation.delay()

    logger.info(
        f"[OrthancSync] created={created} deleted={deleted} skipped={skipped} "
        f"seq={last_seq}->{new_seq}"
    )
    return {
        'status': 'ok',
        'created': created,
        'deleted': deleted,
        'skipped': skipped,
        'seq': new_seq,
    }


@shared_task(name='ophtalmo.tasks.tache_auto_segmentation')
def tache_auto_segmentation():
    """
    Parcourt les examens OP en attente dans la worklist et déclenche
    la segmentation MONAI Label (OD/OC, vaisseaux, lésions) pour chacun.
    Les résultats DICOM-SEG sont automatiquement poussés dans Orthanc
    via le pipeline patché de MONAI Label.
    """
    from .models import Exam

    exams = Exam.objects.filter(
        status='En attente',
        exam_type='Rétinographie',
    )[:5]

    SEG_MODELS = ["optic_disc_cup", "vessel_seg", "lesion_seg"]
    MONAI_LABEL = "http://monai-label:8000"

    for exam in exams:
        study_id = exam.study_instance_uid
        if not study_id:
            continue

        # Vérifier via Orthanc que l'étude a une série OP et récupérer son SeriesInstanceUID
        op_series_uid = None
        try:
            orthanc_resp = requests.get(
                f'{ORTHANC_URL}/studies/{study_id}',
                timeout=10,
            )
            if orthanc_resp.status_code != 200:
                continue
            orthanc_meta = orthanc_resp.json()
            for sid in orthanc_meta.get('Series', []):
                sr = requests.get(f'{ORTHANC_URL}/series/{sid}', timeout=10)
                if sr.status_code == 200:
                    s = sr.json()
                    if s.get('MainDicomTags', {}).get('Modality') == 'OP':
                        op_series_uid = s.get('MainDicomTags', {}).get('SeriesInstanceUID')
                        break
            if not op_series_uid:
                continue
        except Exception as e:
            logger.warning(f"[AutoSeg] Orthanc check failed for {study_id}: {e}")
            continue

        # Lancer les 3 segmentations via MONAI Label
        device = "cuda" if os.environ.get("USE_CUDA", "false") == "true" else "cpu"
        all_ok = True

        for model in SEG_MODELS:
            try:
                logger.info(f"[AutoSeg] Running {model} on series {op_series_uid[:50]}...")
                resp = requests.post(
                    f"{MONAI_LABEL}/infer/{model}",
                    params={"image": op_series_uid},
                    data={"params": f'{{"device": "{device}"}}'},
                    timeout=300,
                )
                if resp.status_code == 200:
                    logger.info(f"[AutoSeg] {model} succeeded")
                else:
                    logger.warning(f"[AutoSeg] {model} returned {resp.status_code}")
                    all_ok = False
            except Exception as e:
                logger.error(f"[AutoSeg] {model} failed: {e}")
                all_ok = False

        if all_ok:
            logger.info(f"[AutoSeg] All segmentations completed for study {study_id}")
