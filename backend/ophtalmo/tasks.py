"""
Tâches Celery pour le système de distribution des examens.
- tache_distribution : distribution immédiate (appelée à chaque nouvel examen)
- tache_verification_24h : vérification périodique des examens en retard (toutes les 24h)
- tache_recalcul_charges : recalcul de sécurité des charges médecins
- tache_sync_orthanc_incremental : synchronisation incrémentale depuis Orthanc (toutes les 60s)
- tache_auto_segmentation : segmentation automatique des nouvelles études OP par MONAI Label
"""
import os
import json
import hashlib
import logging
from datetime import date
import requests
from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)

ORTHANC_URL = os.environ.get('ORTHANC_URL', 'http://orthanc-container:8042')


def inject_op_geometry(orthanc_url, orthanc_series_id, monai_cache_dir=None, orthanc_study_id=None):
    """
    Inject synthetic spatial geometry tags into all DICOM instances of an OP
    (fundus photography) series directly in Orthanc, and make the SeriesInstanceUID
    unique to avoid cross-patient collisions when MONAI Label searches by UID.

    Fundus/OP images typically lack FrameOfReferenceUID, ImagePositionPatient,
    ImageOrientationPatient and PixelSpacing.  Without these, OHIF/Cornerstone3D
    cannot spatially align a generated DICOM-SEG overlay with the source image.

    Additionally, if two different patients share the same SeriesInstanceUID (which
    happens when the same fundus template is uploaded for multiple patients), MONAI
    Label's DICOMweb search by SeriesInstanceUID may return the wrong patient's
    DICOM — causing the SEG to be generated for the wrong patient.  To fix this,
    we append a short hash of the Orthanc study ID to the SeriesInstanceUID, making
    it unique per study.

    Uses Orthanc's /instances/{id}/modify endpoint to avoid changing the
    SOPInstanceUID or file meta information.

    After modification, clears the MONAI Label cache for the old series UID so
    that MONAI Label re-downloads the updated DICOM from Orthanc on next inference.

    Args:
        orthanc_url: Orthanc base URL (e.g. http://orthanc-container:8042)
        orthanc_series_id: Orthanc internal series ID (from /series endpoint)
        monai_cache_dir: Path to MONAI Label DICOM cache (optional, for clearing)
        orthanc_study_id: Orthanc internal study ID (optional, for unique hash)

    Returns:
        tuple: (num_modified, new_series_instance_uid) or (0, original_uid) if
               no modification was needed.
    """
    # List instances in the series
    try:
        resp = requests.get(f'{orthanc_url}/series/{orthanc_series_id}/instances', timeout=15)
        resp.raise_for_status()
        instances = resp.json()
    except requests.RequestException as e:
        logger.warning(f"[GeometryInject] Could not list instances for series {orthanc_series_id}: {e}")
        return 0, None

    # If orthanc_study_id not provided, try to get it from the series metadata
    if not orthanc_study_id:
        try:
            series_meta = requests.get(f'{orthanc_url}/series/{orthanc_series_id}', timeout=10).json()
            orthanc_study_id = series_meta.get('ParentStudy')
        except Exception:
            pass

    modified = 0
    original_series_uid = None
    study_instance_uid = None
    new_series_uid = None

    for inst in instances:
        inst_id = inst.get('ID')
        if not inst_id:
            continue

        # Check if geometry already exists via simplified-tags (lightweight, no download)
        try:
            tags_resp = requests.get(f'{orthanc_url}/instances/{inst_id}/simplified-tags', timeout=15)
            tags_resp.raise_for_status()
            tags = tags_resp.json()
        except requests.RequestException as e:
            logger.warning(f"[GeometryInject] Could not get tags for instance {inst_id}: {e}")
            continue

        sop_uid = tags.get('SOPInstanceUID', inst_id)
        if not original_series_uid:
            original_series_uid = tags.get('SeriesInstanceUID')
            study_instance_uid = tags.get('StudyInstanceUID')

        has_fruid = 'FrameOfReferenceUID' in tags
        has_ipp = 'ImagePositionPatient' in tags

        # Compute a single synthetic FRUID for the entire series (from StudyInstanceUID).
        # A unique per-slice FRUID would break OHIF overlay — all slices must share the same FRUID.
        if not study_instance_uid:
            study_instance_uid = tags.get('StudyInstanceUID')
        synthetic_fruid = "2.25." + str(int(hashlib.md5((study_instance_uid or sop_uid).encode()).hexdigest(), 16))[:39]

        # Generate a unique SeriesInstanceUID by appending a hash of the Orthanc study ID.
        # This prevents cross-patient collisions when MONAI Label searches by SeriesInstanceUID.
        # Orthanc study ID is guaranteed unique, unlike DICOM StudyInstanceUID which can collide.
        if original_series_uid and not new_series_uid:
            uid_for_hash = orthanc_study_id or study_instance_uid or sop_uid
            uid_hash = hashlib.md5(uid_for_hash.encode()).hexdigest()[:8]
            # Only modify if the SeriesInstanceUID doesn't already have the hash suffix
            if not original_series_uid.endswith(uid_hash):
                new_series_uid = f"{original_series_uid}.{uid_hash}"
            else:
                new_series_uid = original_series_uid

        # Build the modify body — always set geometry + SeriesInstanceUID (if new)
        modify_body = {
            "Replace": {
                "FrameOfReferenceUID": synthetic_fruid,
                "ImagePositionPatient": "0\\0\\0",
                "ImageOrientationPatient": "1\\0\\0\\0\\1\\0",
                "SliceThickness": "1",
            },
        }
        if not tags.get('PixelSpacing'):
            modify_body["Replace"]["PixelSpacing"] = "1\\1"
        if new_series_uid and new_series_uid != original_series_uid:
            modify_body["Replace"]["SeriesInstanceUID"] = new_series_uid
            modify_body["Force"] = True

        if not modify_body["Replace"].get("SeriesInstanceUID") and has_fruid and has_ipp:
            # Already has geometry and no SeriesInstanceUID change needed
            logger.debug(f"[GeometryInject] Instance {inst_id} already has geometry, skipping")
            continue

        try:
            mod_resp = requests.post(
                f'{orthanc_url}/instances/{inst_id}/modify',
                json=modify_body,
                timeout=30,
            )
            if mod_resp.status_code != 200:
                logger.warning(
                    f"[GeometryInject] Modify failed for instance {inst_id}: "
                    f"HTTP {mod_resp.status_code} - {mod_resp.text[:200]}"
                )
                continue

            # Orthanc returns the modified DICOM binary (not JSON), so check
            # the status code alone — no need to parse the body.
            logger.info(
                f"[GeometryInject] Modified instance {inst_id} "
                f"(SOP {sop_uid[:40]}...) FRUID={synthetic_fruid[:40]}... "
                f"SeriesUID={new_series_uid or original_series_uid} (HTTP {mod_resp.status_code})"
            )

            # Delete the original instance (the modified one is already in Orthanc)
            try:
                requests.delete(f'{orthanc_url}/instances/{inst_id}', timeout=15)
            except requests.RequestException as e:
                logger.warning(f"[GeometryInject] Could not delete original instance {inst_id}: {e}")

            modified += 1
        except requests.RequestException as e:
            logger.warning(f"[GeometryInject] Modify request failed for instance {inst_id}: {e}")
            continue

    # Determine the final SeriesInstanceUID to return.
    # Only return the new UID if at least one instance was actually modified,
    # otherwise MONAI Label would try to download a non-existent series.
    if modified > 0 and new_series_uid:
        final_series_uid = new_series_uid
    else:
        final_series_uid = original_series_uid

    # Clear MONAI Label cache for BOTH the old and new series UIDs
    if modified > 0 and monai_cache_dir:
        if original_series_uid:
            _clear_monai_cache(monai_cache_dir, original_series_uid, orthanc_url)
        if new_series_uid and new_series_uid != original_series_uid:
            _clear_monai_cache(monai_cache_dir, new_series_uid, orthanc_url)

    logger.info(
        f"[GeometryInject] Series {orthanc_series_id}: {modified}/{len(instances)} instances modified, "
        f"SeriesInstanceUID: {original_series_uid} -> {final_series_uid}"
    )
    return modified, final_series_uid


def _clear_monai_cache(monai_cache_dir, series_instance_uid, orthanc_url=None):
    """Delete cached DICOM + NIfTI files for a series so MONAI Label re-downloads.

    MONAI Label stores its DICOM cache as:
      {monai_cache_dir}/dicom/{md5(orthanc_dicomweb_url)}/{series_instance_uid}/
      {monai_cache_dir}/dicom/{md5(orthanc_dicomweb_url)}/{series_instance_uid}.nii.gz

    If orthanc_url is provided, the hash path is computed directly for efficiency.
    Otherwise, falls back to scanning all hash subdirectories.
    """
    import shutil

    dicom_root = os.path.join(monai_cache_dir, 'dicom')
    if not os.path.isdir(dicom_root):
        logger.warning(f"[GeometryInject] MONAI cache dir not found: {dicom_root}")
        return

    def _clear_path(base_path):
        cleared = 0
        # Delete cached DICOM directory
        if os.path.isdir(base_path):
            shutil.rmtree(base_path, ignore_errors=True)
            cleared += 1
            logger.info(f"[GeometryInject] Cleared MONAI cache: {base_path}")
        # Delete cached NIfTI file
        nii = f"{base_path}.nii.gz"
        if os.path.exists(nii):
            try:
                os.unlink(nii)
                logger.info(f"[GeometryInject] Cleared MONAI NIfTI cache: {nii}")
            except OSError:
                pass
        return cleared

    cleared = 0

    # Fast path: compute the hash directly from orthanc_url
    if orthanc_url:
        dicomweb_url = orthanc_url.rstrip('/') + '/dicom-web'
        uri_hash = hashlib.md5(dicomweb_url.encode('utf-8'), usedforsecurity=False).hexdigest()
        cleared += _clear_path(os.path.join(dicom_root, uri_hash, series_instance_uid))
    else:
        # Fallback: scan all hash subdirectories (slower but works without orthanc_url)
        for hash_dir in os.listdir(dicom_root):
            hash_path = os.path.join(dicom_root, hash_dir)
            if not os.path.isdir(hash_path):
                continue
            cleared += _clear_path(os.path.join(hash_path, series_instance_uid))

    if cleared == 0:
        logger.debug(f"[GeometryInject] No MONAI cache entries found for series {series_instance_uid}")


def _snapshot_seg_series(orthanc_url):
    """Return the set of all Orthanc series IDs with Modality=SEG."""
    seg_ids = set()
    try:
        for sid in requests.get(f'{orthanc_url}/series', timeout=30).json():
            try:
                sr = requests.get(f'{orthanc_url}/series/{sid}', timeout=10)
                if sr.status_code == 200 and sr.json().get('MainDicomTags', {}).get('Modality') == 'SEG':
                    seg_ids.add(sid)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[SegFix] Snapshot error: {e}")
    return seg_ids


def _fix_seg_association(orthanc_url, candidate_ids, expected_patient_id, expected_study_uid):
    """Enforce correct PatientID and StudyInstanceUID on candidate SEG series.

    Uses Orthanc /series/{id}/modify (creates corrected copy), then removes
    the original incorrect series to avoid duplicates in OHIF.
    """
    if not expected_patient_id and not expected_study_uid:
        return
    for sid in candidate_ids:
        try:
            sr = requests.get(f'{orthanc_url}/series/{sid}', timeout=10)
            if sr.status_code != 200:
                continue
            s = sr.json()
            if s.get('MainDicomTags', {}).get('Modality') != 'SEG':
                continue

            dt = s.get('MainDicomTags', {})
            replace = {}
            if expected_patient_id and dt.get('PatientID') != expected_patient_id:
                replace['PatientID'] = expected_patient_id
            if expected_study_uid and dt.get('StudyInstanceUID') != expected_study_uid:
                replace['StudyInstanceUID'] = expected_study_uid

            if not replace:
                continue

            mod = requests.post(
                f'{orthanc_url}/series/{sid}/modify',
                json={'Replace': replace},
                timeout=60,
            )
            if mod.status_code != 200:
                logger.warning(f"[SegFix] Modify failed for SEG series {sid}: {mod.status_code}")
                continue

            del_resp = requests.delete(f'{orthanc_url}/series/{sid}', timeout=30)
            if del_resp.status_code in (200, 204):
                logger.info(f"[SegFix] Fixed SEG series {sid}: {replace}")
            else:
                logger.warning(f"[SegFix] Modified SEG {sid} but could not remove original: {del_resp.status_code}")
        except Exception as e:
            logger.warning(f"[SegFix] Error checking series {sid}: {e}")


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

        # Vérifier que l'étude contient au moins une série OP (fundus)
        # pour éviter la boucle de rétroaction : SEG poussé → webhook → nouveau Exam → nouvelle seg
        series_ids = meta.get('Series', [])
        has_op = False
        for sid in series_ids[:5]:
            try:
                sr = requests.get(f'{ORTHANC_URL}/series/{sid}', timeout=5)
                if sr.status_code == 200 and sr.json().get('MainDicomTags', {}).get('Modality') == 'OP':
                    has_op = True
                    break
            except Exception:
                continue
        if not has_op:
            skipped += 1
            continue

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
        # Déclencher la segmentation automatique pour les nouvelles études
        # (la distribution sera déclenchée après la segmentation)
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
    Parcourt les examens OP en segmentation_status='pending' et déclenche
    la segmentation MONAI Label (OD/OC, vaisseaux, lésions) + classification DR.
    Les résultats DICOM-SEG sont automatiquement poussés dans Orthanc
    via le pipeline patché de MONAI Label.

    Après la segmentation, déclenche la distribution pour que l'examen
    passe de 'En attente' → 'En cours' avec assignation à un médecin.
    """
    from .models import Exam

    MAX_RETRIES = 3
    SEG_MODELS = ["optic_disc_cup", "vessel_seg", "lesion_seg"]
    MONAI_LABEL = "http://monai-label:8000"

    exams = Exam.objects.filter(
        segmentation_status='pending',
        exam_type='Rétinographie',
    ).exclude(
        study_instance_uid__isnull=True,
    ).exclude(
        study_instance_uid__exact='',
    )[:10]

    if not exams:
        return {'status': 'no_pending_exams'}

    device = "cuda" if os.environ.get("USE_CUDA", "false") == "true" else "cpu"
    processed = 0

    for exam in exams:
        study_id = exam.study_instance_uid

        # Mark as in_progress immediately to prevent double-processing
        exam.segmentation_status = 'in_progress'
        exam.save(update_fields=['segmentation_status'])

        # Find OP series within the study
        op_series_uid = None
        op_orthanc_series_id = None
        try:
            orthanc_resp = requests.get(
                f'{ORTHANC_URL}/studies/{study_id}',
                timeout=10,
            )
            if orthanc_resp.status_code != 200:
                exam.segmentation_status = 'failed'
                exam.segmentation_error = f'Orthanc study lookup returned {orthanc_resp.status_code}'
                exam.save(update_fields=['segmentation_status', 'segmentation_error'])
                continue

            orthanc_meta = orthanc_resp.json()
            for sid in orthanc_meta.get('Series', []):
                sr = requests.get(f'{ORTHANC_URL}/series/{sid}', timeout=10)
                if sr.status_code == 200:
                    s = sr.json()
                    if s.get('MainDicomTags', {}).get('Modality') == 'OP':
                        op_series_uid = s.get('MainDicomTags', {}).get('SeriesInstanceUID')
                        op_orthanc_series_id = sid
                        break

            if not op_series_uid:
                exam.segmentation_status = 'completed'
                exam.segmentation_models_status = {'skipped': 'no OP series found'}
                exam.save(update_fields=['segmentation_status', 'segmentation_models_status'])
                continue
        except Exception as e:
            exam.segmentation_status = 'failed'
            exam.segmentation_error = f'Orthanc check failed: {str(e)[:200]}'
            exam.save(update_fields=['segmentation_status', 'segmentation_error'])
            continue

        # Inject synthetic geometry into source OP DICOMs in Orthanc so that
        # the generated SEG shares the same FrameOfReferenceUID and OHIF can
        # spatially align the overlay.  Fundus/OP images lack IPP/IOP/FRUID.
        # Also makes SeriesInstanceUID unique per study to prevent cross-patient
        # collisions when MONAI Label searches by UID.
        # Also clears the MONAI Label cache so it re-downloads the updated DICOM.
        if op_orthanc_series_id:
            monai_cache = os.environ.get('MONAI_CACHE_DIR', '/root/.cache/monailabel')
            try:
                _, new_series_uid = inject_op_geometry(ORTHANC_URL, op_orthanc_series_id, monai_cache, study_id)
            except Exception as e:
                logger.error(f"[AutoSeg] Geometry injection exception for study {study_id}: {e}")
                exam.segmentation_status = 'failed'
                exam.segmentation_error = f'Geometry injection exception: {str(e)[:200]}'
                exam.save(update_fields=['segmentation_status', 'segmentation_error'])
                continue
            if not new_series_uid:
                logger.error(f"[AutoSeg] inject_op_geometry returned no SeriesInstanceUID for study {study_id}")
                exam.segmentation_status = 'failed'
                exam.segmentation_error = 'Geometry injection returned no SeriesInstanceUID'
                exam.save(update_fields=['segmentation_status', 'segmentation_error'])
                continue
            op_series_uid = new_series_uid

            # Nuclear option: blow away the entire MONAI Label DICOM cache so it
            # MUST re-download the geometry-injected instances fresh.
            try:
                import shutil
                dicom_root = os.path.join(monai_cache, 'dicom')
                if os.path.isdir(dicom_root):
                    shutil.rmtree(dicom_root, ignore_errors=True)
                    logger.info(f"[AutoSeg] Cleared entire MONAI DICOM cache: {dicom_root}")
            except Exception as e:
                logger.warning(f"[AutoSeg] Could not clear DICOM cache: {e}")

        # Get the DICOM StudyInstanceUID to ensure SEG lands in the same study
        op_study_uid = orthanc_meta.get('MainDicomTags', {}).get('StudyInstanceUID', '')
        expected_patient_id = orthanc_meta.get('PatientMainDicomTags', {}).get('PatientID', '')
        base_params = {"device": device}
        if op_study_uid:
            base_params["study_uid"] = op_study_uid

        # Snapshot existing SEG series so we can find only the new one after inference
        seg_ids_before = _snapshot_seg_series(ORTHANC_URL)

        # Run all segmentation models
        models_status = {}
        all_ok = True

        for model in SEG_MODELS:
            try:
                logger.info(f"[AutoSeg] Running {model} on series {op_series_uid[:50]}...")
                resp = requests.post(
                    f"{MONAI_LABEL}/infer/{model}",
                    params={"image": op_series_uid},
                    data={"params": json.dumps(base_params)},
                    timeout=300,
                )
                if resp.status_code == 200:
                    models_status[model] = 'ok'
                    logger.info(f"[AutoSeg] {model} succeeded for study {study_id}")
                else:
                    models_status[model] = f'failed (HTTP {resp.status_code})'
                    logger.warning(f"[AutoSeg] {model} returned {resp.status_code} for study {study_id}")
                    all_ok = False
            except Exception as e:
                models_status[model] = f'failed ({str(e)[:100]})'
                logger.error(f"[AutoSeg] {model} failed for study {study_id}: {e}")
                all_ok = False

        # Run DR classification
        try:
            logger.info(f"[AutoSeg] Running dr_classification on series {op_series_uid[:50]}...")
            resp = requests.post(
                f"{MONAI_LABEL}/infer/dr_classification",
                params={"image": op_series_uid},
                data={"params": json.dumps(base_params)},
                timeout=120,
            )
            if resp.status_code == 200:
                models_status['dr_classification'] = 'ok'
                logger.info(f"[AutoSeg] dr_classification succeeded for study {study_id}")
            else:
                models_status['dr_classification'] = f'failed (HTTP {resp.status_code})'
                logger.warning(f"[AutoSeg] dr_classification returned {resp.status_code}")
        except Exception as e:
            models_status['dr_classification'] = f'failed ({str(e)[:100]})'
            logger.error(f"[AutoSeg] dr_classification failed for study {study_id}: {e}")

        # Fix SEG patient/study association in Orthanc — safety net for any patch failures
        try:
            seg_ids_after = _snapshot_seg_series(ORTHANC_URL)
            new_seg_ids = seg_ids_after - seg_ids_before
            if new_seg_ids:
                _fix_seg_association(ORTHANC_URL, new_seg_ids, expected_patient_id, op_study_uid)
                logger.info(f"[AutoSeg] Checked {len(new_seg_ids)} new SEG series for study {study_id}")
        except Exception as e:
            logger.warning(f"[AutoSeg] SEG association fix failed for study {study_id}: {e}")

        # Update exam based on results
        exam.segmentation_models_status = models_status
        exam.segmentation_retries += 1

        if all_ok:
            exam.segmentation_status = 'completed'
            exam.segmentation_error = ''
            logger.info(f"[AutoSeg] All segmentations completed for study {study_id}")
        else:
            # Partial failure: retry up to MAX_RETRIES times
            if exam.segmentation_retries >= MAX_RETRIES:
                exam.segmentation_status = 'failed'
                failed_models = [m for m, s in models_status.items() if s != 'ok']
                exam.segmentation_error = f'Échec après {MAX_RETRIES} tentatives: {", ".join(failed_models)}'
                logger.warning(
                    f"[AutoSeg] Giving up on study {study_id} after {MAX_RETRIES} retries. "
                    f"Failed models: {failed_models}"
                )
            else:
                exam.segmentation_status = 'pending'
                logger.info(
                    f"[AutoSeg] Study {study_id} will retry (attempt {exam.segmentation_retries}/{MAX_RETRIES})"
                )

        exam.save(update_fields=[
            'segmentation_status', 'segmentation_retries',
            'segmentation_error', 'segmentation_models_status',
        ])
        processed += 1

    return {'processed': processed}
