"""
Tâches Celery pour le système de distribution des examens.
- tache_distribution : distribution immédiate (appelée à chaque nouvel examen)
- tache_verification_24h : vérification périodique des examens en retard (toutes les 24h)
- tache_recalcul_charges : recalcul de sécurité des charges médecins
- tache_sync_orthanc_incremental : synchronisation incrémentale depuis Orthanc (toutes les 60s)
- tache_auto_quality : évaluation automatique FTHNet des images OP
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
from django.db import transaction
from .dicom_patient import patient_metadata

logger = logging.getLogger(__name__)

ORTHANC_URL = os.environ.get('ORTHANC_URL', 'http://orthanc-container:8042')


def _monai_label_ready(monai_label_url, timeout=5):
    """Return True only when MONAI Label is accepting API requests."""
    for path in ('/info', '/monai/info', '/'):
        try:
            resp = requests.get(f'{monai_label_url}{path}', timeout=timeout)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            continue
    return False


def _resolve_orthanc_id(dicom_study_uid):
    """Convert a DICOM StudyInstanceUID to an Orthanc internal study ID."""
    try:
        resp = requests.post(
            f'{ORTHANC_URL}/tools/find',
            json={'Level': 'Study', 'Query': {'StudyInstanceUID': dicom_study_uid}},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return results[0]
    except Exception:
        pass
    # Fallback: maybe the stored value IS already an Orthanc ID (legacy records)
    return dicom_study_uid


_fthnet_predictor = None


def _get_fthnet_predictor():
    """Load FTHNet once per Celery worker process."""
    global _fthnet_predictor
    if _fthnet_predictor is None:
        from .fthnet_cpu import FTHNetCPU
        _fthnet_predictor = FTHNetCPU()
    return _fthnet_predictor


def inject_op_geometry(orthanc_url, orthanc_series_id, monai_cache_dir=None, orthanc_study_id=None):
    """
    Inject synthetic spatial geometry tags into all DICOM instances of an OP
    (fundus photography) series directly in Orthanc.

    Fundus/OP images typically lack FrameOfReferenceUID, ImagePositionPatient,
    ImageOrientationPatient and PixelSpacing.  Without these, OHIF/Cornerstone3D
    cannot spatially align a generated DICOM-SEG overlay with the source image.

    Uses Orthanc's /instances/{id}/modify endpoint to avoid changing the
    SOPInstanceUID or file meta information.

    After modification, clears the MONAI Label cache for the series UID so
    that MONAI Label re-downloads the updated DICOM from Orthanc on next inference.

    Args:
        orthanc_url: Orthanc base URL (e.g. http://orthanc-container:8042)
        orthanc_series_id: Orthanc internal series ID (from /series endpoint)
        monai_cache_dir: Path to MONAI Label DICOM cache (optional, for clearing)
        orthanc_study_id: Orthanc internal study ID (optional)

    Returns:
        tuple: (num_modified, series_instance_uid) or (0, None) if
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

        # Build the modify body — inject geometry tags only (keep original SeriesInstanceUID)
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

        if has_fruid and has_ipp:
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
                f"SeriesUID={original_series_uid} (HTTP {mod_resp.status_code})"
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

    # Return the original SeriesInstanceUID (unchanged)
    final_series_uid = original_series_uid

    # Clear MONAI Label cache for the series UID
    if modified > 0 and monai_cache_dir:
        if original_series_uid:
            _clear_monai_cache(monai_cache_dir, original_series_uid, orthanc_url)

    logger.info(
        f"[GeometryInject] Series {orthanc_series_id}: {modified}/{len(instances)} instances modified, "
        f"SeriesInstanceUID: {final_series_uid}"
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


def _fix_seg_association(
    orthanc_url,
    candidate_ids,
    expected_patient_id,
    expected_study_uid,
    expected_series_uid=None,
):
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

            # Never modify a SEG that explicitly references another source
            # series. This protects unrelated studies if another producer adds
            # a SEG between the before/after snapshots.
            if expected_series_uid and s.get('Instances'):
                tags_resp = requests.get(
                    f"{orthanc_url}/instances/{s['Instances'][0]}/tags?simplify",
                    timeout=10,
                )
                if tags_resp.status_code == 200:
                    referenced_uids = {
                        item.get('SeriesInstanceUID')
                        for item in tags_resp.json().get('ReferencedSeriesSequence', [])
                        if isinstance(item, dict)
                    }
                    referenced_uids.discard(None)
                    if referenced_uids and expected_series_uid not in referenced_uids:
                        logger.warning(
                            "[SegFix] Ignoring SEG %s: references %s, expected %s",
                            sid,
                            sorted(referenced_uids),
                            expected_series_uid,
                        )
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


def _collect_op_series(orthanc_url, orthanc_study_id):
    """Return every OP series in a study as Orthanc ID + DICOM SeriesInstanceUID."""
    resp = requests.get(f'{orthanc_url}/studies/{orthanc_study_id}', timeout=10)
    resp.raise_for_status()
    study = resp.json()
    op_series = []

    for sid in study.get('Series', []):
        sr = requests.get(f'{orthanc_url}/series/{sid}', timeout=10)
        if sr.status_code != 200:
            continue
        series = sr.json()
        tags = series.get('MainDicomTags', {}) or {}
        if str(tags.get('Modality', '')).upper() != 'OP':
            continue
        series_uid = tags.get('SeriesInstanceUID')
        if not series_uid:
            logger.warning("[OPSeries] Skipping OP series %s without SeriesInstanceUID", sid)
            continue
        op_series.append({
            'orthanc_series_id': sid,
            'series_instance_uid': series_uid,
        })

    return study, op_series


def _prepare_monai_series_cache(orthanc_url, orthanc_series_id, series_instance_uid, study_id):
    """Populate MONAI's DICOM cache with the exact Orthanc source series."""
    import shutil

    monai_cache = os.environ.get('MONAI_CACHE_DIR', '/root/.cache/monailabel')
    dicom_root = os.path.join(monai_cache, 'dicom')
    if os.path.isdir(dicom_root):
        shutil.rmtree(dicom_root, ignore_errors=True)
        logger.info("[AutoSeg] Cleared MONAI DICOM cache: %s", dicom_root)

    dicomweb_url = 'http://orthanc-container:8042/dicom-web'
    cache_hash = hashlib.md5(dicomweb_url.encode()).hexdigest()
    cache_dir = os.path.join(dicom_root, cache_hash, series_instance_uid)
    os.makedirs(cache_dir, exist_ok=True)

    series_detail = requests.get(
        f'{orthanc_url}/series/{orthanc_series_id}',
        timeout=30,
    )
    series_detail.raise_for_status()
    instances = series_detail.json().get('Instances', [])
    for instance_id in instances:
        instance_resp = requests.get(
            f'{orthanc_url}/instances/{instance_id}/file',
            timeout=30,
        )
        instance_resp.raise_for_status()
        with open(os.path.join(cache_dir, f'{instance_id}.dcm'), 'wb') as output:
            output.write(instance_resp.content)

    logger.info(
        "[AutoSeg] Cached exact source series %s from study %s (%s instance(s))",
        series_instance_uid,
        study_id,
        len(instances),
    )


def _run_eye_laterality(monai_label_url, series_instance_uid, base_params):
    """Run optional eye laterality classifier and normalize its response."""
    resp = requests.post(
        f"{monai_label_url}/infer/eye_laterality",
        params={"image": series_instance_uid},
        data={"params": json.dumps(base_params)},
        timeout=120,
    )
    if resp.status_code != 200:
        return {'status': f'failed (HTTP {resp.status_code})'}

    payload = resp.json()
    params = payload.get('params', payload) if isinstance(payload, dict) else {}
    laterality = (
        params.get('laterality')
        or params.get('eye_laterality')
        or params.get('prediction')
        or ''
    )
    confidence = (
        params.get('laterality_confidence')
        or params.get('confidence')
        or params.get('score')
    )
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = None

    return {
        'status': 'ok',
        'laterality': laterality,
        'confidence': confidence,
        'low_confidence': confidence is not None and confidence < 0.80,
        'probabilities': params.get('laterality_probabilities'),
    }


def _failed_model_names(models_status):
    failed = []
    for series_uid, series_status in models_status.items():
        if not isinstance(series_status, dict):
            if series_status not in ('ok', 'manual'):
                failed.append(str(series_uid))
            continue
        for model, model_status in series_status.items():
            if model == 'eye_laterality' and isinstance(model_status, dict):
                if model_status.get('status') not in ('ok', 'skipped'):
                    failed.append(f'{series_uid}:eye_laterality')
                continue
            if model_status not in ('ok', 'manual'):
                failed.append(f'{series_uid}:{model}')
    return failed


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
            orthanc_id = change.get('ID')
            if orthanc_id:
                # Try deleting by Orthanc internal ID (legacy) and also
                # look up the DICOM UID from Orthanc to match new records.
                # Since the study is already deleted, we try both approaches.
                deleted_qs = Exam.objects.filter(study_instance_uid=orthanc_id)
                if not deleted_qs.exists():
                    # New-style record: the UID stored is the DICOM UID, not Orthanc ID.
                    # We can't look it up because the study is deleted.
                    # Just skip — this is a rare edge case.
                    pass
                else:
                    AnalysisReport.objects.filter(series_instance_uid=orthanc_id).delete()
                    deleted_qs.delete()
                    deleted += 1
            continue

        if change_type != 'NewStudy':
            continue

        study_id = change.get('ID')  # Orthanc internal ID
        if not study_id:
            continue

        try:
            detail = requests.get(f'{ORTHANC_URL}/studies/{study_id}', timeout=15)
            detail.raise_for_status()
            meta = detail.json()
        except requests.RequestException:
            skipped += 1
            continue

        patient = patient_metadata(meta)

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
        dicom_study_uid = main_dicom.get('StudyInstanceUID', study_id)
        institution = main_dicom.get('InstitutionName', '')
        region = institution if institution else ''

        # Check for duplicates using the real DICOM UID
        if Exam.objects.filter(study_instance_uid=dicom_study_uid).exists():
            skipped += 1
            continue
        # Also check legacy records that stored Orthanc internal ID
        if Exam.objects.filter(study_instance_uid=study_id).exists():
            skipped += 1
            continue

        Exam.objects.create(
            study_instance_uid=dicom_study_uid,
            **patient,
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
        # FTHNet runs first; it starts segmentation when quality is persisted.
        tache_auto_quality.delay()

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


@shared_task(name='ophtalmo.tasks.tache_auto_quality')
def tache_auto_quality():
    """Evaluate every OP instance in new Orthanc exams with FTHNet on CPU."""
    from .models import Exam, ImageQualityAssessment

    exams = Exam.objects.filter(
        quality_status='pending',
        exam_type='Rétinographie',
    ).exclude(
        study_instance_uid__isnull=True,
    ).exclude(
        study_instance_uid__exact='',
    )[:10]

    if not exams:
        return {'status': 'no_pending_exams'}

    predictor = _get_fthnet_predictor()
    processed = 0
    images_analyzed = 0

    for exam in exams:
        exam.quality_status = 'in_progress'
        exam.quality_error = ''
        exam.save(update_fields=['quality_status', 'quality_error'])

        try:
            orthanc_id = _resolve_orthanc_id(exam.study_instance_uid)
            study_response = requests.get(
                f'{ORTHANC_URL}/studies/{orthanc_id}',
                timeout=30,
            )
            study_response.raise_for_status()
            study = study_response.json()
            expected_study_uid = (
                study.get('MainDicomTags', {}).get('StudyInstanceUID', '')
            )
            expected_patient_id = (
                study.get('PatientMainDicomTags', {}).get('PatientID', '')
            )
            instance_ids = []

            for series_id in study.get('Series', []):
                series_response = requests.get(
                    f'{ORTHANC_URL}/series/{series_id}', timeout=30
                )
                series_response.raise_for_status()
                series = series_response.json()
                modality = str(
                    series.get('MainDicomTags', {}).get('Modality', '')
                ).upper()
                if modality == 'OP':
                    instance_ids.extend(series.get('Instances', []))

            if not instance_ids:
                raise ValueError('Aucune instance DICOM de modalité OP trouvée')

            results = []
            for instance_id in instance_ids:
                result = predictor.predict_orthanc_instance(
                    instance_id, ORTHANC_URL
                )
                sop_uid = result.get('sop_instance_uid')
                if not sop_uid:
                    raise ValueError(
                        f'SOPInstanceUID absent pour instance {instance_id}'
                    )
                actual_study_uid = result.get('study_instance_uid', '')
                actual_patient_id = result.get('patient_id', '')
                if expected_study_uid and actual_study_uid != expected_study_uid:
                    raise ValueError(
                        'Résultat qualité associé à une autre étude: '
                        f'attendu {expected_study_uid}, reçu {actual_study_uid}'
                    )
                if expected_patient_id and actual_patient_id != expected_patient_id:
                    raise ValueError(
                        'Résultat qualité associé à un autre patient: '
                        f'attendu {expected_patient_id}, reçu {actual_patient_id}'
                    )
                results.append((instance_id, result))

            # Persist only after every result has passed the identity checks,
            # so a partially analyzed exam can never display another study.
            with transaction.atomic():
                for instance_id, result in results:
                    ImageQualityAssessment.objects.update_or_create(
                        sop_instance_uid=result['sop_instance_uid'],
                        defaults={
                            'exam': exam,
                            'orthanc_instance_id': instance_id,
                            'study_instance_uid': result.get('study_instance_uid', ''),
                            'series_instance_uid': result.get('series_instance_uid', ''),
                            'patient_id': result.get('patient_id', ''),
                            'modality': 'OP',
                            'score': result['score'],
                            'category': result['category'],
                        },
                    )
                    images_analyzed += 1

            summary = min((result for _, result in results), key=lambda item: item['score'])
            exam.quality_score = summary['score']
            exam.quality_category = summary['category']
            exam.quality_status = 'completed'
            exam.quality_error = ''
            exam.save(update_fields=[
                'quality_score', 'quality_category',
                'quality_status', 'quality_error',
            ])
            processed += 1
            logger.info(
                f"[FTHNet] Exam {exam.id}: {len(results)} OP image(s), "
                f"minimum score={summary['score']} ({summary['category']})"
            )
        except Exception as exc:
            exam.quality_status = 'failed'
            exam.quality_error = str(exc)[:1000]
            exam.save(update_fields=['quality_status', 'quality_error'])
            logger.exception(f"[FTHNet] Quality analysis failed for exam {exam.id}")
            processed += 1

    # A quality failure does not block the existing clinical segmentation.
    if processed:
        tache_auto_segmentation.delay()

    return {'processed': processed, 'images_analyzed': images_analyzed}


@shared_task(name='ophtalmo.tasks.tache_auto_segmentation')
def tache_auto_segmentation():
    """
    Parcourt les examens OP en segmentation_status='pending' et déclenche
    la segmentation MONAI Label (OD/OC, vaisseaux, lésions), la classification
    DR par œil, puis un brouillon de compte rendu IA.
    Les résultats DICOM-SEG sont automatiquement poussés dans Orthanc
    via le pipeline patché de MONAI Label.

    Après la segmentation, déclenche la distribution pour que l'examen
    passe de 'En attente' → 'En cours' avec assignation à un médecin.
    """
    from .analysis_utils import aggregate_per_eye, worst_dr_confidence
    from .models import AnalysisReport, Exam, MedicalReport, MedicalReportVersion
    from .report_utils import build_ai_report_text

    MAX_RETRIES = 3
    SEG_MODELS = ["optic_disc_cup", "vessel_seg", "lesion_seg"]
    MONAI_LABEL = "http://monai-label:8000"

    # MONAI's DICOM cache and the Orthanc SEG snapshot are shared resources.
    # Prevent Celery Beat and a chained backfill task from processing two
    # batches concurrently and racing over that cache.
    lock_key = 'ophtalmo:auto_segmentation_running'
    if not cache.add(lock_key, '1', timeout=20 * 60):
        return {'status': 'already_running'}

    if not _monai_label_ready(MONAI_LABEL):
        cache.delete(lock_key)
        logger.info("[AutoSeg] MONAI Label is not ready; keeping pending exams queued")
        return {'status': 'monai_not_ready'}

    exams = Exam.objects.filter(
        segmentation_status='pending',
        exam_type='Rétinographie',
        quality_status__in=['completed', 'failed'],
    ).exclude(
        study_instance_uid__isnull=True,
    ).exclude(
        study_instance_uid__exact='',
    )[:10]

    if not exams:
        cache.delete(lock_key)
        return {'status': 'no_pending_exams'}

    device = "cuda" if os.environ.get("USE_CUDA", "false") == "true" else "cpu"
    processed = 0

    for exam in exams:
        study_id = exam.study_instance_uid
        orthanc_study_id = _resolve_orthanc_id(study_id)

        # Mark as in_progress immediately to prevent double-processing
        exam.segmentation_status = 'in_progress'
        exam.save(update_fields=['segmentation_status'])

        # Find every OP series within the study. Each eye can arrive as a
        # separate OP series, so stopping at the first one skips the other eye.
        try:
            orthanc_meta, op_series = _collect_op_series(ORTHANC_URL, orthanc_study_id)
            if not op_series:
                exam.segmentation_status = 'completed'
                exam.segmentation_models_status = {'skipped': 'no OP series found'}
                exam.save(update_fields=['segmentation_status', 'segmentation_models_status'])
                continue
        except Exception as e:
            exam.segmentation_status = 'failed'
            exam.segmentation_error = f'Orthanc check failed: {str(e)[:200]}'
            exam.save(update_fields=['segmentation_status', 'segmentation_error'])
            continue

        # Get the DICOM StudyInstanceUID to ensure SEG lands in the same study
        op_study_uid = orthanc_meta.get('MainDicomTags', {}).get('StudyInstanceUID', '')
        expected_patient_id = orthanc_meta.get('PatientMainDicomTags', {}).get('PatientID', '')
        base_params = {"device": device}
        if op_study_uid:
            base_params["study_uid"] = op_study_uid

        models_status = {}
        series_reports = {}
        all_ok = True

        for op_series_item in op_series:
            op_series_uid = op_series_item['series_instance_uid']
            op_orthanc_series_id = op_series_item['orthanc_series_id']
            series_status = {}

            try:
                # SeriesInstanceUID is not always unique in imported synthetic
                # OP files. Populate MONAI's cache from this exact Orthanc
                # series so DICOMweb cannot select the same UID from another
                # patient/study.
                _prepare_monai_series_cache(
                    ORTHANC_URL,
                    op_orthanc_series_id,
                    op_series_uid,
                    study_id,
                )
            except Exception as e:
                series_status['cache'] = f'failed ({str(e)[:100]})'
                models_status[op_series_uid] = series_status
                all_ok = False
                logger.exception("[AutoSeg] Could not prepare exact MONAI source")
                continue

            try:
                series_status['eye_laterality'] = _run_eye_laterality(
                    MONAI_LABEL,
                    op_series_uid,
                    base_params,
                )
            except Exception as e:
                # Laterality should be visible in status, but should not block
                # the clinical segmentation pipeline for this eye.
                series_status['eye_laterality'] = f'failed ({str(e)[:100]})'
                logger.warning(
                    "[AutoSeg] eye_laterality failed for series %s: %s",
                    op_series_uid,
                    e,
                )

            # Snapshot per source series so SEGs created for one eye are fixed
            # only against that eye's referenced source series.
            seg_ids_before = _snapshot_seg_series(ORTHANC_URL)

            for model in SEG_MODELS:
                try:
                    logger.info("[AutoSeg] Running %s on series %s...", model, op_series_uid[:50])
                    resp = requests.post(
                        f"{MONAI_LABEL}/infer/{model}",
                        params={"image": op_series_uid},
                        data={"params": json.dumps(base_params)},
                        timeout=300,
                    )
                    if resp.status_code == 200:
                        series_status[model] = 'ok'
                        logger.info("[AutoSeg] %s succeeded for series %s", model, op_series_uid)
                    else:
                        series_status[model] = f'failed (HTTP {resp.status_code})'
                        logger.warning(
                            "[AutoSeg] %s returned %s for series %s",
                            model,
                            resp.status_code,
                            op_series_uid,
                        )
                        all_ok = False
                except Exception as e:
                    series_status[model] = f'failed ({str(e)[:100]})'
                    logger.error("[AutoSeg] %s failed for series %s: %s", model, op_series_uid, e)
                    all_ok = False

            try:
                analyze_resp = requests.post(
                    f"{MONAI_LABEL}/infer/analyze",
                    json={
                        "image": op_series_uid,
                        "run_segmentation": True,
                        "push_dicom_seg": False,
                        "study_uid": op_study_uid or study_id,
                    },
                    timeout=300,
                )
                if analyze_resp.status_code == 200:
                    analysis = analyze_resp.json()
                    analysis["eye_laterality"] = series_status.get("eye_laterality")
                    series_reports[op_series_uid] = analysis
                    series_status['dr_classification'] = 'ok'
                else:
                    series_status['dr_classification'] = f'failed (HTTP {analyze_resp.status_code})'
                    logger.warning(
                        "[AutoSeg] /infer/analyze returned %s for series %s",
                        analyze_resp.status_code,
                        op_series_uid,
                    )
            except Exception as e:
                series_status['dr_classification'] = f'failed ({str(e)[:100]})'
                logger.warning("[AutoSeg] /infer/analyze failed for series %s: %s", op_series_uid, e)

            # Fix SEG patient/study association in Orthanc — safety net for any patch failures
            try:
                seg_ids_after = _snapshot_seg_series(ORTHANC_URL)
                new_seg_ids = seg_ids_after - seg_ids_before
                if new_seg_ids:
                    _fix_seg_association(
                        ORTHANC_URL,
                        new_seg_ids,
                        expected_patient_id,
                        op_study_uid,
                        op_series_uid,
                    )
                    logger.info(
                        "[AutoSeg] Checked %s new SEG series for source series %s",
                        len(new_seg_ids),
                        op_series_uid,
                    )
                else:
                    all_ok = False
                    series_status['dicom_seg'] = 'failed (no DICOM-SEG created)'
                    logger.error(
                        "[AutoSeg] MONAI returned success but created no DICOM-SEG for series %s",
                        op_series_uid,
                    )
            except Exception as e:
                all_ok = False
                series_status['dicom_seg'] = f'failed ({str(e)[:100]})'
                logger.warning(
                    "[AutoSeg] SEG association fix failed for series %s: %s",
                    op_series_uid,
                    e,
                )

            models_status[op_series_uid] = series_status

        per_eye = aggregate_per_eye(series_reports)
        if per_eye:
            reports_by_eye = {}
            report_generation_status = "skipped"
            report_generation_error = ""
            try:
                eye_texts = []
                report_errors = []
                for side in ("right", "left"):
                    eye_report = per_eye.get(side)
                    if not eye_report:
                        continue
                    eye_label = "Œil droit" if side == "right" else "Œil gauche"
                    try:
                        generated = build_ai_report_text(
                            expected_patient_id or exam.patient_id,
                            eye_report,
                            eye_label,
                            patient_age=exam.patient_age,
                        )
                    except Exception as e:
                        report_errors.append(f"{eye_label}: {str(e)[:200]}")
                        logger.warning(
                            "[AutoSeg] AI draft report generation failed for %s: %s",
                            eye_label,
                            e,
                        )
                        continue
                    reports_by_eye[side] = {
                        "eye": eye_label,
                        "report_text": generated.get("report_text") or "",
                        "report_html": generated.get("report_html") or "",
                        "report_json": generated.get("report_json") or {},
                        "status": "generated",
                    }
                    text = generated.get("report_text") or ""
                    if text:
                        eye_texts.append(f"{eye_label}:\n{text}")

                if eye_texts:
                    report_generation_status = (
                        "completed" if len(reports_by_eye) == len(per_eye) and not report_errors else "partial"
                    )
                    report_generation_error = "; ".join(report_errors)
                    combined = "\n\n".join(eye_texts)
                    ai_report_data = {
                        "per_eye": per_eye,
                        "reports_by_eye": reports_by_eye,
                    }
                    report = (
                        MedicalReport.objects.filter(
                            examination_id=str(exam.id),
                            status=MedicalReport.Status.AI_GENERATED,
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    if report:
                        report.patient_id = expected_patient_id or exam.patient_id
                        report.ai_content = combined
                        report.ai_confidence = worst_dr_confidence(per_eye)
                        report.ai_report_data = ai_report_data
                        report.save(
                            update_fields=[
                                "patient_id",
                                "ai_content",
                                "ai_confidence",
                                "ai_report_data",
                                "updated_at",
                            ]
                        )
                        MedicalReportVersion.objects.filter(report=report, version_number=1).delete()
                    else:
                        report = MedicalReport.objects.create(
                            patient_id=expected_patient_id or exam.patient_id,
                            examination_id=str(exam.id),
                            generated_by_ai=True,
                            status=MedicalReport.Status.AI_GENERATED,
                            ai_content=combined,
                            ai_confidence=worst_dr_confidence(per_eye),
                            ai_report_data=ai_report_data,
                        )
                    MedicalReportVersion.objects.create(
                        report=report,
                        version_number=1,
                        content=combined,
                        version_type=MedicalReportVersion.VersionType.AI,
                    )
                else:
                    report_generation_status = "failed"
                    report_generation_error = (
                        "; ".join(report_errors) or "Report generator returned empty content"
                    )
            except Exception as e:
                report_generation_status = "failed"
                report_generation_error = str(e)[:500]
                logger.warning("[AutoSeg] AI draft report generation skipped: %s", e)

            report_json = {
                "source": "monai_label_auto",
                "status": "AI_ANALYZED",
                "study_instance_uid": study_id,
                "series_reports": series_reports,
                "per_eye": per_eye,
                "reports_by_eye": reports_by_eye,
                "report_generation_status": report_generation_status,
                "report_generation_error": report_generation_error,
            }
            analysis_report = AnalysisReport.objects.filter(series_instance_uid=study_id).first()
            if analysis_report:
                analysis_report.user = None
                analysis_report.report_json = report_json
                analysis_report.save(update_fields=["user", "report_json"])
            else:
                AnalysisReport.objects.create(
                    series_instance_uid=study_id,
                    user=None,
                    report_json=report_json,
                )

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
                failed_models = _failed_model_names(models_status)
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

    # Déclencher la distribution pour assigner les examens terminés (ou échoués) aux médecins
    if processed > 0:
        tache_distribution.delay()

    # This task intentionally processes at most 10 exams per invocation. Keep
    # draining the queue so a backfill of existing OP studies does not stop
    # after the first batch.
    more_pending = Exam.objects.filter(
        segmentation_status='pending',
        exam_type='Rétinographie',
        quality_status__in=['completed', 'failed'],
    ).exclude(
        study_instance_uid__isnull=True,
    ).exclude(
        study_instance_uid__exact='',
    ).exists()
    if more_pending:
        tache_auto_segmentation.apply_async(countdown=2)

    cache.delete(lock_key)
    return {'processed': processed}
