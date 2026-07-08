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


AI_SEG_SERIES_DESCRIPTIONS = {"optic_disc_cup", "vessel_seg", "lesion_seg"}


def _delete_prior_ai_seg_series(
    orthanc_url,
    orthanc_study_id,
    source_series_uid,
    model_names=None,
):
    """Delete old AI-generated SEG series for one OP source series.

    This prevents repeated automatic/manual AI runs from accumulating duplicate
    DICOM-SEG series in Orthanc. It only deletes SEG series whose description is
    one of our AI model names and whose ReferencedSeriesSequence points back to
    the exact source OP SeriesInstanceUID.
    """
    if not orthanc_study_id or not source_series_uid:
        return 0

    allowed_descriptions = set(model_names or AI_SEG_SERIES_DESCRIPTIONS)
    deleted = 0

    try:
        study_resp = requests.get(f'{orthanc_url}/studies/{orthanc_study_id}', timeout=15)
        study_resp.raise_for_status()
        series_ids = study_resp.json().get('Series', [])
    except requests.RequestException as e:
        logger.warning("[SegCleanup] Could not list study %s: %s", orthanc_study_id, e)
        return 0

    for sid in series_ids:
        try:
            series_resp = requests.get(f'{orthanc_url}/series/{sid}', timeout=10)
            if series_resp.status_code != 200:
                continue
            series = series_resp.json()
            tags = series.get('MainDicomTags', {}) or {}
            if tags.get('Modality') != 'SEG':
                continue
            if tags.get('SeriesDescription') not in allowed_descriptions:
                continue

            instances = series.get('Instances') or []
            if not instances:
                continue
            tags_resp = requests.get(
                f"{orthanc_url}/instances/{instances[0]}/tags?simplify",
                timeout=10,
            )
            if tags_resp.status_code != 200:
                continue

            referenced_uids = {
                item.get('SeriesInstanceUID')
                for item in (tags_resp.json().get('ReferencedSeriesSequence') or [])
                if isinstance(item, dict)
            }
            referenced_uids.discard(None)
            if source_series_uid not in referenced_uids:
                continue

            delete_resp = requests.delete(f'{orthanc_url}/series/{sid}', timeout=30)
            if delete_resp.status_code in (200, 204):
                deleted += 1
                logger.info(
                    "[SegCleanup] Deleted prior %s SEG series %s for source %s",
                    tags.get('SeriesDescription'),
                    sid,
                    source_series_uid,
                )
            else:
                logger.warning(
                    "[SegCleanup] Failed deleting SEG series %s: HTTP %s",
                    sid,
                    delete_resp.status_code,
                )
        except Exception as e:
            logger.warning("[SegCleanup] Error checking SEG series %s: %s", sid, e)

    return deleted


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
            'dicom_laterality': _series_dicom_laterality(orthanc_url, sid, series),
        })

    return study, op_series


def _normalize_laterality(value):
    if not value:
        return ''
    value = str(value).strip().upper()
    value = value.replace('\\', '/')
    if value in {'L', 'LEFT', 'OS', 'OG'}:
        return 'L'
    if value in {'R', 'RIGHT', 'OD'}:
        return 'R'
    tokens = [token for token in value.replace('-', '/').replace('_', '/').split('/') if token]
    if tokens:
        if tokens[-1] in {'L', 'LEFT', 'OS', 'OG'}:
            return 'L'
        if tokens[-1] in {'R', 'RIGHT', 'OD'}:
            return 'R'
    return ''


def _series_dicom_laterality(orthanc_url, orthanc_series_id, series=None):
    """Read trusted eye laterality from OP DICOM metadata when available."""
    try:
        series = series or requests.get(
            f'{orthanc_url}/series/{orthanc_series_id}',
            timeout=10,
        ).json()
        tags = series.get('MainDicomTags', {}) or {}
        laterality = _normalize_laterality(
            tags.get('ImageLaterality')
            or tags.get('Laterality')
            or tags.get('SeriesDescription')
        )
        if laterality:
            return laterality

        for instance_id in series.get('Instances', [])[:8]:
            resp = requests.get(
                f'{orthanc_url}/instances/{instance_id}/simplified-tags',
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            tags = resp.json() or {}
            laterality = _normalize_laterality(
                tags.get('ImageLaterality')
                or tags.get('Laterality')
                or tags.get('SeriesDescription')
            )
            if laterality:
                return laterality
    except Exception as exc:
        logger.debug(
            "[OPSeries] Could not read DICOM laterality for series %s: %s",
            orthanc_series_id,
            exc,
        )
    return ''


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


def _run_eye_laterality(monai_label_url, series_instance_uid, base_params, dicom_laterality=''):
    """Run optional eye laterality classifier and normalize its response."""
    dicom_laterality = _normalize_laterality(dicom_laterality)
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
    model_laterality = _normalize_laterality(laterality) or laterality
    confidence = (
        params.get('laterality_confidence')
        or params.get('confidence')
        or params.get('score')
    )
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = None

    final_laterality = dicom_laterality or model_laterality
    if dicom_laterality and model_laterality and dicom_laterality != model_laterality:
        logger.warning(
            "[EyeLaterality] DICOM laterality %s overrides model %s for series %s "
            "(model confidence=%s)",
            dicom_laterality,
            model_laterality,
            series_instance_uid,
            confidence,
        )

    return {
        'status': 'ok',
        'laterality': final_laterality,
        'confidence': confidence,
        'low_confidence': confidence is not None and confidence < 0.80,
        'laterality_source': 'dicom' if dicom_laterality else 'model',
        'dicom_laterality': dicom_laterality or None,
        'model_laterality': model_laterality,
        'model_confidence': confidence,
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

    logger.info("[AutoSeg] === Démarrage de la tâche de segmentation automatique ===")

    # ==========================================
    # ÉTAPE 1 : Gestion du verrou de concurrence
    # ==========================================
    lock_key = 'ophtalmo:auto_segmentation_running'
    if not cache.add(lock_key, '1', timeout=20 * 60):
        logger.warning("[AutoSeg] Tâche déjà en cours d'exécution (verrou actif). Annulation de cette instance.")
        return {'status': 'already_running'}

    # ==========================================
    # ÉTAPE 2 : Vérification de la santé de l'IA
    # ==========================================
    logger.debug(f"[AutoSeg] Vérification de la disponibilité du serveur MONAI Label à l'adresse : {MONAI_LABEL}")
    if not _monai_label_ready(MONAI_LABEL):
        cache.delete(lock_key)
        logger.error("[AutoSeg] Le serveur MONAI Label n'est pas prêt ou injoignable. Libération du verrou.")
        return {'status': 'monai_not_ready'}

    # ==========================================
    # ÉTAPE 3 : Sélection du lot d'examens (Batch)
    # ==========================================
    logger.debug("[AutoSeg] Recherche d'examens en attente de segmentation...")
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
        logger.info("[AutoSeg] Aucun examen en attente de segmentation. Fin de la tâche et libération du verrou.")
        return {'status': 'no_pending_exams'}

    logger.info(f"[AutoSeg] {len(exams)} examen(s) trouvé(s) à traiter dans ce lot.")

    # Configuration du matériel d'exécution (CPU/GPU)
    device = "cuda" if os.environ.get("USE_CUDA", "false") == "true" else "cpu"
    logger.info(f"[AutoSeg] Utilisation du matériel d'exécution d'IA sélectionné : {device.upper()}")
    processed = 0

    # ==========================================
    # ÉTAPE 4 : Boucle principale sur chaque examen
    # ==========================================
    for exam in exams:
        study_id = exam.study_instance_uid
        orthanc_study_id = _resolve_orthanc_id(study_id)

        logger.info(
            f"[AutoSeg] [Examen {exam.id}] Début du traitement - Patient: {exam.patient_name} (ID: {exam.patient_id}) - "
            f"StudyInstanceUID: {study_id} (ID Interne Orthanc: {orthanc_study_id})"
        )

        # Passage du statut à "En cours" pour verrouiller l'examen en base de données
        exam.segmentation_status = 'in_progress'
        exam.save(update_fields=['segmentation_status'])
        logger.debug(f"[Examen {exam.id}] Statut mis à jour à 'in_progress' en base de données.")

        # Récupération des séries de type rétinographie (OP) depuis Orthanc
        try:
            logger.debug(f"[Examen {exam.id}] Collecte des séries de rétinographie (OP) dans Orthanc...")
            orthanc_meta, op_series = _collect_op_series(ORTHANC_URL, orthanc_study_id)
            if not op_series:
                logger.warning(
                    f"[Examen {exam.id}] Aucune série de modalité OP trouvée dans l'étude {orthanc_study_id}. "
                    "Marquage comme 'completed' (sans analyse)."
                )
                exam.segmentation_status = 'completed'
                exam.segmentation_models_status = {'skipped': 'no OP series found'}
                exam.save(update_fields=['segmentation_status', 'segmentation_models_status'])
                continue
            logger.info(f"[Examen {exam.id}] {len(op_series)} série(s) OP détectée(s) pour traitement.")
        except Exception as e:
            logger.error(
                f"[Examen {exam.id}] Échec de la vérification ou de la communication avec Orthanc : {str(e)}", 
                exc_info=True
            )
            exam.segmentation_status = 'failed'
            exam.segmentation_error = f'Orthanc check failed: {str(e)[:200]}'
            exam.save(update_fields=['segmentation_status', 'segmentation_error'])
            continue

        # Extraction des métadonnées requises pour la cohérence
        op_study_uid = orthanc_meta.get('MainDicomTags', {}).get('StudyInstanceUID', '')
        expected_patient_id = orthanc_meta.get('PatientMainDicomTags', {}).get('PatientID', '')
        base_params = {"device": device}
        if op_study_uid:
            base_params["study_uid"] = op_study_uid

        models_status = {}
        series_reports = {}
        all_ok = True

        # ==========================================
        # ÉTAPE 5 : Analyse série par série (oeil par oeil)
        # ==========================================
        for op_series_item in op_series:
            op_series_uid = op_series_item['series_instance_uid']
            op_orthanc_series_id = op_series_item['orthanc_series_id']
            series_status = {}

            logger.info(
                f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Début du traitement oeil - "
                f"ID Interne Série Orthanc: {op_orthanc_series_id}"
            )

            # Étape A : Synchronisation du cache DICOM de MONAI
            try:
                logger.debug(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Synchronisation du cache MONAI local...")
                _prepare_monai_series_cache(
                    ORTHANC_URL,
                    op_orthanc_series_id,
                    op_series_uid,
                    study_id,
                )
                logger.debug(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Cache synchronisé avec succès.")
            except Exception as e:
                logger.error(
                    f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Échec de la préparation du cache : {str(e)}", 
                    exc_info=True
                )
                series_status['cache'] = f'failed ({str(e)[:100]})'
                models_status[op_series_uid] = series_status
                all_ok = False
                continue

            # Étape B : Classification de la latéralité (Oeil gauche vs Oeil droit)
            try:
                logger.info(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Exécution du classifieur de latéralité de l'oeil...")
                lat_result = _run_eye_laterality(
                    MONAI_LABEL,
                    op_series_uid,
                    base_params,
                    dicom_laterality=op_series_item.get('dicom_laterality'),
                )
                series_status['eye_laterality'] = lat_result
                logger.info(
                    f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Résultat latéralité : "
                    f"Latéralité={lat_result.get('laterality')} (Confiance: {lat_result.get('confidence')})"
                )
            except Exception as e:
                series_status['eye_laterality'] = f'failed ({str(e)[:100]})'
                logger.warning(
                    f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Le modèle de latéralité a échoué : {str(e)}",
                    exc_info=True
                )

            # Étape C : Capture des segmentations pré-existantes (Snapshot avant traitement)
            deleted_prior_seg = _delete_prior_ai_seg_series(
                ORTHANC_URL,
                orthanc_study_id,
                op_series_uid,
                SEG_MODELS,
            )
            if deleted_prior_seg:
                logger.info(
                    f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] "
                    f"{deleted_prior_seg} ancien(s) DICOM-SEG IA supprimé(s) avant régénération."
                )

            seg_ids_before = _snapshot_seg_series(ORTHANC_URL)
            logger.debug(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Instantané Orthanc pré-traitement : {len(seg_ids_before)} segmentations détectées.")

            # Étape D : Passage des modèles de segmentation d'IA (OD/OC, Vaisseaux, Lésions)
            for model in SEG_MODELS:
                try:
                    logger.info(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Lancement du modèle : {model}")
                    resp = requests.post(
                        f"{MONAI_LABEL}/infer/{model}",
                        params={"image": op_series_uid},
                        data={"params": json.dumps(base_params)},
                        timeout=300,
                    )
                    if resp.status_code == 200:
                        series_status[model] = 'ok'
                        logger.info(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Modèle {model} exécuté avec succès.")
                    else:
                        series_status[model] = f'failed (HTTP {resp.status_code})'
                        all_ok = False
                        logger.warning(
                            f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Le modèle {model} a échoué. "
                            f"Code HTTP de retour : {resp.status_code} - Réponse : {resp.text[:200]}"
                        )
                except Exception as e:
                    series_status[model] = f'failed ({str(e)[:100]})'
                    all_ok = False
                    logger.error(
                        f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Erreur système lors du modèle {model} : {str(e)}",
                        exc_info=True
                    )

            # Étape E : Lancement de l'analyse globale et classification DR (Rétinopathie)
            try:
                logger.info(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Lancement de la classification globale (rétinopathie)...")
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
                    logger.info(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Classification globale terminée avec succès.")
                else:
                    series_status['dr_classification'] = f'failed (HTTP {analyze_resp.status_code})'
                    logger.warning(
                        f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] L'analyse globale a échoué. "
                        f"Code HTTP de retour : {analyze_resp.status_code}"
                    )
            except Exception as e:
                series_status['dr_classification'] = f'failed ({str(e)[:100]})'
                logger.error(
                    f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Erreur système lors de l'analyse globale : {str(e)}",
                    exc_info=True
                )

            # Étape F : Sécurisation et correction d'association des fichiers DICOM-SEG créés
            try:
                logger.debug(f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Détection et correction des métadonnées des nouveaux fichiers SEG...")
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
                        f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] {len(new_seg_ids)} fichier(s) DICOM-SEG associé(s) "
                        f"avec succès au patient {expected_patient_id}."
                    )
                else:
                    all_ok = False
                    series_status['dicom_seg'] = 'failed (no DICOM-SEG created)'
                    logger.error(
                        f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Succès d'exécution indiqué par l'IA, "
                        f"mais aucune nouvelle série DICOM-SEG n'a été détectée dans Orthanc."
                    )
            except Exception as e:
                all_ok = False
                series_status['dicom_seg'] = f'failed ({str(e)[:100]})'
                logger.error(
                    f"[Examen {exam.id}] [Série {op_series_uid[:15]}...] Erreur critique lors de la correction du fichier DICOM-SEG : {str(e)}",
                    exc_info=True
                )

            models_status[op_series_uid] = series_status

        # ==========================================
        # ÉTAPE 6 : Agrégation et écriture des rapports d'analyse
        # ==========================================
        per_eye = aggregate_per_eye(series_reports)
        if per_eye:
            logger.info(f"[Examen {exam.id}] Données d'IA agrégées avec succès par oeil. Début de la rédaction du projet de compte rendu...")
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
                        logger.debug(f"[Examen {exam.id}] Génération du compte rendu IA écrit pour l'œil : {eye_label}")
                        generated = build_ai_report_text(
                            expected_patient_id or exam.patient_id,
                            eye_report,
                            eye_label,
                            patient_age=exam.patient_age,
                        )
                    except Exception as e:
                        report_errors.append(f"{eye_label}: {str(e)[:200]}")
                        logger.warning(
                            f"[Examen {exam.id}] Échec de génération de texte pour {eye_label} : {str(e)}",
                            exc_info=True
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

                    # Enregistrement ou mise à jour du MedicalReport en base de données
                    report = (
                        MedicalReport.objects.filter(
                            examination_id=str(exam.id),
                            status=MedicalReport.Status.AI_GENERATED,
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    
                    if report:
                        logger.info(f"[Examen {exam.id}] Mise à jour du MedicalReport existant (ID: {report.id}).")
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
                        # On supprime la v1 existante pour la remplacer par la nouvelle version d'IA fraîchement générée
                        MedicalReportVersion.objects.filter(report=report, version_number=1).delete()
                    else:
                        logger.info(f"[Examen {exam.id}] Création d'un nouveau MedicalReport d'analyse automatique.")
                        report = MedicalReport.objects.create(
                            patient_id=expected_patient_id or exam.patient_id,
                            examination_id=str(exam.id),
                            generated_by_ai=True,
                            status=MedicalReport.Status.AI_GENERATED,
                            ai_content=combined,
                            ai_confidence=worst_dr_confidence(per_eye),
                            ai_report_data=ai_report_data,
                        )

                    # Création de la version historique officielle n°1 du rapport (Généré par l'IA)
                    MedicalReportVersion.objects.create(
                        report=report,
                        version_number=1,
                        content=combined,
                        version_type=MedicalReportVersion.VersionType.AI,
                    )
                    logger.info(f"[Examen {exam.id}] Version 1 (AI) du compte rendu médical enregistrée en base de données.")
                else:
                    report_generation_status = "failed"
                    report_generation_error = (
                        "; ".join(report_errors) or "Le générateur de rapport a renvoyé un contenu vide."
                    )
                    logger.warning(f"[Examen {exam.id}] Rédaction de compte rendu annulée ou vide : {report_generation_error}")
            except Exception as e:
                report_generation_status = "failed"
                report_generation_error = str(e)[:500]
                logger.error(f"[Examen {exam.id}] Échec critique lors de l'écriture du rapport d'IA : {str(e)}", exc_info=True)

            # Enregistrement des données JSON techniques d'analyse globale
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
                logger.debug(f"[Examen {exam.id}] Mise à jour de la table AnalysisReport technique pour l'étude : {study_id}")
                analysis_report.user = None
                analysis_report.report_json = report_json
                analysis_report.save(update_fields=["user", "report_json"])
            else:
                logger.debug(f"[Examen {exam.id}] Création d'une nouvelle entrée AnalysisReport technique pour l'étude : {study_id}")
                AnalysisReport.objects.create(
                    series_instance_uid=study_id,
                    user=None,
                    report_json=report_json,
                )

        # ==========================================
        # ÉTAPE 7 : Finalisation de l'état de l'examen
        # ==========================================
        exam.segmentation_models_status = models_status
        exam.segmentation_retries += 1

        if all_ok:
            exam.segmentation_status = 'completed'
            exam.segmentation_error = ''
            logger.info(f"[Examen {exam.id}] Succès de l'analyse IA. Examen configuré sur 'completed'.")
        else:
            # En cas de dysfonctionnement partiel, l'examen peut retenter l'analyse
            if exam.segmentation_retries >= MAX_RETRIES:
                exam.segmentation_status = 'failed'
                failed_models = _failed_model_names(models_status)
                exam.segmentation_error = f'Échec après {MAX_RETRIES} tentatives: {", ".join(failed_models)}'
                logger.error(
                    f"[Examen {exam.id}] Abandon de la segmentation après {MAX_RETRIES} tentatives d'analyse. "
                    f"Modèles d'IA en échec : {failed_models}"
                )
            else:
                exam.segmentation_status = 'pending'
                logger.warning(
                    f"[Examen {exam.id}] Échec partiel d'analyse. L'examen sera replacé en attente (pending) "
                    f"pour une nouvelle tentative (Essai {exam.segmentation_retries}/{MAX_RETRIES})"
                )

        exam.save(update_fields=[
            'segmentation_status', 'segmentation_retries',
            'segmentation_error', 'segmentation_models_status',
        ])
        processed += 1

    # ==========================================
    # ÉTAPE 8 : Actions post-lot (Distribution et récurrence)
    # ==========================================
    if processed > 0:
        logger.info(f"[AutoSeg] Fin de l'analyse du lot. Déclenchement de la distribution des examens aux médecins...")
        tache_distribution.delay()

    # Vérification s'il reste d'autres examens dans la file d'attente globale
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
        logger.info("[AutoSeg] Des examens en attente sont encore présents. Planification automatique du prochain lot de segmentation (countdown=2s).")
        tache_auto_segmentation.apply_async(countdown=2)
    else:
        logger.info("[AutoSeg] File d'attente de segmentation entièrement vide.")

    # Libération finale du verrou
    cache.delete(lock_key)
    logger.info("[AutoSeg] Libération du verrou. Fin d'exécution de la tâche.")
    return {'processed': processed}
