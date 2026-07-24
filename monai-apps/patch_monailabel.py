"""Apply patches to MONAI Label installed package for DICOM-SEG + Orthanc push."""
import os

CONVERT = "/usr/local/lib/python3.10/dist-packages/monailabel/datastore/utils/convert.py"
INFER = "/usr/local/lib/python3.10/dist-packages/monailabel/endpoints/infer.py"

patches_applied = False

# Patch 1: convert.py - synthetic geometry, FRUID hash, FRUID save/restore, mask dim fix
# (Legacy patterns – kept for older image versions that still have the for-loop form)
if os.path.exists(CONVERT):
    with open(CONVERT) as f:
        content = f.read()
    changes = []
    if 'return ""' in content:
        content = content.replace('return ""', 'return None')
        changes.append("convert.py: return '' -> None")
    if 'logger.error("Missing Attributes/Empty Label provided")' in content:
        content = content.replace(
            'logger.error("Missing Attributes/Empty Label provided")',
            'logger.warning("Missing Attributes/Empty Label provided")'
        )
        changes.append("convert.py: error -> warning for empty seg")

    # Replace for-loop DICOM read with list comprehension + geometry injection + FRUID hash
    old_read = '''        image_datasets = []
        for f in image_files:
            ds = dcmread(str(f), stop_before_pixels=True)
            if not hasattr(ds, 'ImagePositionPatient'):
                ds.ImagePositionPatient = [0, 0, 0]
            if not hasattr(ds, 'ImageOrientationPatient'):
                ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            if not hasattr(ds, 'SliceThickness'):
                ds.SliceThickness = 1.0
            if not hasattr(ds, 'SpacingBetweenSlices'):
                ds.SpacingBetweenSlices = 1.0
            image_datasets.append(ds)
        logger.info(f"Total Source Images: {len(image_datasets)}")'''
    new_read = '''        image_datasets = [dcmread(str(f), stop_before_pixels=True) for f in image_files]
        logger.info(f"Total Source Images: {len(image_datasets)}")

        # Inject synthetic geometry tags for non-standard modalities (OP fundus, etc.)
        import hashlib
        for ds in image_datasets:
            if not hasattr(ds, "ImagePositionPatient"):
                ds.ImagePositionPatient = [0, 0, 0]
            if not hasattr(ds, "ImageOrientationPatient"):
                ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            if not hasattr(ds, "SliceThickness"):
                ds.SliceThickness = 1.0
            if not hasattr(ds, "SpacingBetweenSlices"):
                ds.SpacingBetweenSlices = 1.0
            has_fruid = hasattr(ds, "FrameOfReferenceUID")
            if has_fruid:
                logger.info(f'FRUID already present on source: {ds.FrameOfReferenceUID}')
            else:
                new_fruid = "2.25." + str(int(hashlib.md5(str(ds.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
                ds.FrameOfReferenceUID = new_fruid
                logger.info(f'Set FRUID on source: {new_fruid}')
            logger.info(f'SOP: {ds.SOPInstanceUID}')'''
    if old_read in content:
        content = content.replace(old_read, new_read)
        changes.append("convert.py: list comprehension + geometry injection + FRUID hash")
    else:
        print("INFO: convert.py for-loop read pattern not found (already patched or different version)")

    # Fix: reshape label mask if dimensions don't match source DICOMs
    old_mask = '''        mask = SimpleITK.ReadImage(label)
        mask = SimpleITK.Cast(mask, SimpleITK.sitkUInt16)

        output_file = tempfile.NamedTemporaryFile(suffix=".dcm").name'''
    new_mask = '''        mask = SimpleITK.ReadImage(label)
        mask = SimpleITK.Cast(mask, SimpleITK.sitkUInt16)

        # Fix dimension mismatch: mask z may not match source instance count
        if image_datasets:
            ref = image_datasets[0]
            expected = (len(image_datasets), int(ref.Rows), int(ref.Columns))
            mask_arr = SimpleITK.GetArrayFromImage(mask)
            if mask_arr.shape != expected and mask_arr.size == np.prod(expected):
                import itertools
                for perm in itertools.permutations(range(mask_arr.ndim)):
                    t = np.transpose(mask_arr, perm)
                    if t.shape == expected:
                        mask = SimpleITK.GetImageFromArray(t.astype(np.uint16))
                        logger.info(f"Reshaped mask {mask_arr.shape} -> {expected} via perm {perm}")
                        break

        output_file = tempfile.NamedTemporaryFile(suffix=".dcm").name'''
    if old_mask in content:
        content = content.replace(old_mask, new_mask)
        changes.append("convert.py: added label mask dimension mismatch fix")

    # Fix: save/restore FRUID around writer.write (pydicom_seg overwrites FRUID)
    old_write = '''        dcm = writer.write(mask, image_datasets)
        dcm.save_as(output_file)'''
    new_write = '''        # Save source FRUID before write (pydicom_seg shares DataElement references)
        expected_fruid = str(image_datasets[0].FrameOfReferenceUID) if image_datasets and hasattr(image_datasets[0], 'FrameOfReferenceUID') else None
        dcm = writer.write(mask, image_datasets)
        if expected_fruid:
            dcm.FrameOfReferenceUID = expected_fruid
            logger.info(f'Set SEG FRUID: {expected_fruid}')
        else:
            logger.warning('Could not set SEG FRUID (no source FRUID available)')
        dcm.save_as(output_file)'''
    if old_write in content:
        content = content.replace(old_write, new_write)
        changes.append("convert.py: FRUID save/restore around writer.write()")

    if changes:
        with open(CONVERT, "w") as f:
            f.write(content)
        print(" | ".join(changes))
        patches_applied = True

# Patch 9: OHIF compatibility — geometry injection into ALL source DICOMs + StudyUID post-process
# Targets the CURRENT installed state: list-comprehension read + existing FRUID save/restore.
# Root causes addressed:
#   Cause 2: geometry injection missing from ALL source datasets (only reads stop_before_pixels)
#   Cause 3: StudyInstanceUID not enforced on output SEG after writer.write()
OHIF_GEOM_MARKER = "### OHIF_GEOM_ALL ###"
if os.path.exists(CONVERT):
    with open(CONVERT) as f:
        content = f.read()

    if OHIF_GEOM_MARKER not in content:
        _p9_changed = False

        # Fix A: Inject geometry into ALL source datasets after list-comprehension read.
        # The current installed code reads with stop_before_pixels=True but never
        # injects ImagePositionPatient / FrameOfReferenceUID — causing pydicom_seg
        # to fail for OP/fundus images that lack these mandatory spatial tags.
        old_geom = '''        image_datasets = [dcmread(str(f), stop_before_pixels=True) for f in image_files]
        logger.info(f"Total Source Images: {len(image_datasets)}")'''
        new_geom = '''        image_datasets = [dcmread(str(f), stop_before_pixels=True) for f in image_files]
        logger.info(f"Total Source Images: {len(image_datasets)}")

        ### OHIF_GEOM_ALL ###
        # Inject synthetic geometry into ALL source datasets lacking spatial tags.
        # Fundus / OP images have no ImagePositionPatient or FrameOfReferenceUID;
        # pydicom_seg needs these to build PerFrameFunctionalGroupsSequence correctly.
        import hashlib as _ohif_hl
        _src_study_uid_geom = None
        _fruid_9a = None
        for _gi, _gds in enumerate(image_datasets):
            # Capture StudyInstanceUID from first source for post-processing
            if _src_study_uid_geom is None and hasattr(_gds, "StudyInstanceUID"):
                _src_study_uid_geom = str(_gds.StudyInstanceUID)
            # Assign a single FrameOfReferenceUID for the entire series (from first SOP UID)
            if _fruid_9a is None and hasattr(_gds, "SOPInstanceUID"):
                _fruid_9a = "2.25." + str(int(_ohif_hl.md5(str(_gds.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
            if not hasattr(_gds, "FrameOfReferenceUID"):
                _gds.FrameOfReferenceUID = _fruid_9a
                logger.info(f"Injected FRUID on src[{_gi}]: {_gds.FrameOfReferenceUID}")
            if not hasattr(_gds, "ImagePositionPatient"):
                _gds.ImagePositionPatient = [0.0, 0.0, float(_gi)]
                _gds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
                _gds.SliceThickness = 1.0
                _gds.SpacingBetweenSlices = 1.0
                logger.info(f"Injected IPP/IOP/thickness on src[{_gi}]")'''
        if old_geom in content:
            content = content.replace(old_geom, new_geom)
            _p9_changed = True
            print("convert.py Patch 9A: geometry injection into ALL source datasets applied")
        else:
            print("WARNING: Patch 9A — list-comprehension read pattern not found in convert.py")

        # Fix B: Post-process output SEG to enforce StudyInstanceUID from source.
        # pydicom_seg may not copy StudyInstanceUID correctly, causing OHIF to miss
        # the SEG when browsing a study (OHIF only loads SEGs within the open study).
        old_save_dcm = '''        if expected_fruid:
            dcm.FrameOfReferenceUID = expected_fruid
            logger.info(f'Set SEG FRUID: {expected_fruid}')
        else:
            logger.warning('Could not set SEG FRUID (no source FRUID available)')
        dcm.save_as(output_file)'''
        new_save_dcm = '''        if expected_fruid:
            dcm.FrameOfReferenceUID = expected_fruid
            logger.info(f'Set SEG FRUID: {expected_fruid}')
        else:
            logger.warning('Could not set SEG FRUID (no source FRUID available)')
        # OHIF fix: enforce StudyInstanceUID from source so SEG appears in same study
        if _src_study_uid_geom and (not hasattr(dcm, 'StudyInstanceUID') or str(dcm.StudyInstanceUID) != _src_study_uid_geom):
            dcm.StudyInstanceUID = _src_study_uid_geom
            logger.info(f'Set SEG StudyInstanceUID: {_src_study_uid_geom}')
        # OHIF fix: enforce PatientID / PatientName from source if present
        _src_ds0 = image_datasets[0] if image_datasets else None
        if _src_ds0 and hasattr(_src_ds0, 'PatientID'):
            dcm.PatientID = str(_src_ds0.PatientID)
        if _src_ds0 and hasattr(_src_ds0, 'PatientName'):
            dcm.PatientName = str(_src_ds0.PatientName)
        # OHIF fix: enforce ReferencedSeriesSequence SeriesInstanceUID from source
        if _src_ds0 and hasattr(_src_ds0, "SeriesInstanceUID") and hasattr(dcm, "ReferencedSeriesSequence"):
            for _rs in dcm.ReferencedSeriesSequence:
                if hasattr(_rs, "SeriesInstanceUID"):
                    _rs.SeriesInstanceUID = str(_src_ds0.SeriesInstanceUID)
                    logger.info(f"Fixed SEG ReferencedSeriesSequence SeriesUID: {_src_ds0.SeriesInstanceUID}")
        # OHIF fix: brute-force enforce ALL ReferencedSOPInstanceUID values in
        # functional groups sequences.  Uses a recursive walker to find every
        # ReferencedSOPInstanceUID regardless of the DICOM path structure,
        # and always sets it to the correct source SOP UID by frame index.
        if image_datasets:
            _p10_sop_list = [str(ds.SOPInstanceUID) for ds in image_datasets if hasattr(ds, "SOPInstanceUID")]
            if _p10_sop_list:
                # Validate frame count
                if hasattr(dcm, "PerFrameFunctionalGroupsSequence"):
                    _nf = len(dcm.PerFrameFunctionalGroupsSequence)
                    _ns = len(_p10_sop_list)
                    if _nf != _ns:
                        logger.warning(
                            f"Frame count mismatch: SEG has {_nf} frames "
                            f"but source has {_ns} images"
                        )

                def _force_fix_sop_refs(_item, _frame_idx, _sop_list):
                    """Recursively find and brute-force set ALL ReferencedSOPInstanceUID
                    values to match the source SOP UID at _frame_idx, regardless of
                    the DICOM path structure."""
                    _expected = _sop_list[_frame_idx] if _frame_idx < len(_sop_list) else _sop_list[0]
                    _count = 0
                    for _elem in _item:
                        if _elem.keyword == "ReferencedSOPInstanceUID":
                            _old_val = str(_elem.value)
                            if _old_val != _expected:
                                _elem.value = _expected
                                _count += 1
                                logger.info(
                                    f"SEG Frame {_frame_idx}: Forced ReferencedSOPInstanceUID "
                                    f"{_old_val[:60]}... -> {_expected[:60]}..."
                                )
                            else:
                                _count += 1
                        elif _elem.VR == "SQ" and _elem.value is not None:
                            for _sub_item in _elem.value:
                                _count += _force_fix_sop_refs(_sub_item, _frame_idx, _sop_list)
                    return _count

                _total_fixes = 0
                # Fix PerFrameFunctionalGroupsSequence
                if hasattr(dcm, "PerFrameFunctionalGroupsSequence"):
                    for _p10_fi, _p10_fg in enumerate(dcm.PerFrameFunctionalGroupsSequence):
                        _total_fixes += _force_fix_sop_refs(_p10_fg, _p10_fi, _p10_sop_list)

                # Fix SharedFunctionalGroupsSequence (apply to all frames)
                if hasattr(dcm, "SharedFunctionalGroupsSequence"):
                    for _sfg in dcm.SharedFunctionalGroupsSequence:
                        for _sfi in range(len(_p10_sop_list)):
                            _total_fixes += _force_fix_sop_refs(_sfg, _sfi, _p10_sop_list)

                if _total_fixes > 0:
                    logger.info(f"SEG: Fixed {_total_fixes} ReferencedSOPInstanceUID references")
        dcm.save_as(output_file)'''
        if old_save_dcm in content:
            content = content.replace(old_save_dcm, new_save_dcm)
            _p9_changed = True
            print("convert.py Patch 9B: StudyUID/SOPUID post-processing added")
        else:
            print("WARNING: Patch 9B — FRUID save pattern not found in convert.py (check Patch 1 applied)")

        if _p9_changed:
            with open(CONVERT, "w") as f:
                f.write(content)
            print("convert.py: OHIF geometry+StudyUID fixes applied (Patch 9)")
            patches_applied = True
    else:
        patches_applied = True  # Patch 9 already applied
        print("convert.py: Patch 9 already applied")

# Patch 2: infer.py - fix label_info fallback + use_itk=False + send_response fallback
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    did_patch = False

    # Fix 1: label_info should fallback to result params
    content = content.replace(
        'elif p.get("label_info") is None:',
        'elif p.get("label_info") is None and result.get("params", {}).get("label_info") is None:',
    )

    # Fix 2: use label_info from request or result params
    content = content.replace(
        'p.get("label_info")',
        'p.get("label_info") or result.get("params", {}).get("label_info")',
    )

    # Fix 2b: use use_itk=False (no itkimage2segimage CLI available)
    content = content.replace(
        'use_itk=True',
        'use_itk=False',
    )

    # Fix 2c: send_response fallback when dicom_seg is None
    content = content.replace(
        'raise HTTPException(status_code=500, detail="Error processing inference")',
        'logger.warning("DICOM-SEG not generated (empty mask or error); falling back to normal response"); return res_json',
    )

    # Fix 3: add Orthanc push if not already present
    if "Pushed DICOM-SEG to Orthanc" not in content:
        old = 'result["dicom_seg"] = dicom_seg_file'
        new = '''if dicom_seg_file and os.path.exists(dicom_seg_file):
            try:
                orthanc_url = "http://orthanc-container:8042/instances"
                with open(dicom_seg_file, "rb") as f:
                    resp = requests.post(orthanc_url, data=f, headers={"Content-Type": "application/dicom"})
                    logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")
            except Exception as e:
                logger.error(f"Failed to push DICOM-SEG to Orthanc: {e}")
            result["dicom_seg"] = dicom_seg_file
        else:
            result.pop("dicom_seg", None)'''
        content = content.replace(old, new)
        if "import requests" not in content:
            content = content.replace("import json", "import json\nimport requests")
        did_patch = True

    if did_patch or content != open(INFER).read():
        with open(INFER, "w") as f:
            f.write(content)
        print("infer.py: label_info fallback + Orthanc push applied")
        patches_applied = True
    else:
        if "Pushed DICOM-SEG to Orthanc" in content:
            patches_applied = True

# Patch 3: Auto-push DICOM-SEG to Orthanc with pre-inject geometry BEFORE SEG gen
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    marker = "### AUTO_PUSH_DICOM_SEG ###"
    if marker not in content:
        old = '''    logger.info(f"Infer Request: {request}")
    result = instance.infer(request)
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to execute infer")'''
        new = '''    logger.info(f"Infer Request: {request}")
    result = instance.infer(request)
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to execute infer")

    ### AUTO_PUSH_DICOM_SEG ###
    import pathlib
    import hashlib
    from pydicom import dcmread
    if isinstance(instance.datastore(), DICOMWebDatastore):
        try:
            res_img = result.get("file") or result.get("label")
            label_info = p.get("label_info") or result.get("params", {}).get("label_info")
            if res_img and os.path.exists(res_img) and label_info:
                image_uri = instance.datastore().get_image_uri(image)
                image_path = next((image_uri.replace(s, "") for s in [".nii", ".nii.gz", ".nrrd"] if image_uri.endswith(s)), "")
                if image_path and os.path.isdir(image_path):
                    # Pre-inject geometry into cached source BEFORE SEG generation
                    try:
                        dcm_files = list(pathlib.Path(image_path).glob("*"))
                        if dcm_files:
                            src_path = str(dcm_files[0])
                            src_ds = dcmread(src_path, stop_before_pixels=True)
                            needs_ipp = not hasattr(src_ds, 'ImagePositionPatient')
                            if not hasattr(src_ds, 'FrameOfReferenceUID') or needs_ipp:
                                src_full = dcmread(src_path)
                                if not hasattr(src_full, 'FrameOfReferenceUID'):
                                    src_full.FrameOfReferenceUID = "2.25." + str(int(hashlib.md5(str(src_full.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
                                if needs_ipp:
                                    src_full.ImagePositionPatient = [0, 0, 0]
                                    src_full.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                                    src_full.SliceThickness = 1.0
                                src_full.save_as(src_path)
                                with open(src_path, "rb") as f:
                                    resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                                logger.info(f"Pre-injected geometry into source (resp={resp.status_code})")
                    except Exception as e2:
                        logger.warning(f"Pre-inject geometry skipped: {e2}")

                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:
                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")
                        os.unlink(dicom_seg_file)
        except Exception as e:
            logger.error(f"Failed to push DICOM-SEG to Orthanc: {e}")'''

        if old in content:
            content = content.replace(old, new)
            with open(INFER, "w") as f:
                f.write(content)
            print("infer.py: auto-push DICOM-SEG added (pre-inject BEFORE SEG gen)")
            patches_applied = True

# Patch 4: Upgrade existing auto-push block with pre-inject BEFORE SEG gen (correct order)
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    if "### AUTO_PUSH_DICOM_SEG ###" in content and "Pre-inject geometry into cached source" not in content:
        # Move the push AFTER pre-inject: find the block that does push then inject
        old = '''                if image_path and os.path.isdir(image_path):
                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:
                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")

                        os.unlink(dicom_seg_file)'''
        new = '''                if image_path and os.path.isdir(image_path):
                    # Pre-inject geometry into cached source BEFORE SEG generation
                    try:
                        dcm_files = list(pathlib.Path(image_path).glob("*"))
                        if dcm_files:
                            src_path = str(dcm_files[0])
                            src_ds = dcmread(src_path, stop_before_pixels=True)
                            needs_ipp = not hasattr(src_ds, 'ImagePositionPatient')
                            if not hasattr(src_ds, 'FrameOfReferenceUID') or needs_ipp:
                                src_full = dcmread(src_path)
                                if not hasattr(src_full, 'FrameOfReferenceUID'):
                                    src_full.FrameOfReferenceUID = "2.25." + str(int(hashlib.md5(str(src_full.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
                                if needs_ipp:
                                    src_full.ImagePositionPatient = [0, 0, 0]
                                    src_full.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                                    src_full.SliceThickness = 1.0
                                src_full.save_as(src_path)
                                with open(src_path, "rb") as f:
                                    resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                                logger.info(f"Pre-injected geometry into source (resp={resp.status_code})")
                    except Exception as e2:
                        logger.warning(f"Pre-inject geometry skipped: {e2}")

                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:
                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")
                        os.unlink(dicom_seg_file)'''
        if "from pydicom import dcmread" not in content:
            content = content.replace(
                "import pathlib",
                "import pathlib\nimport hashlib\nfrom pydicom import dcmread"
            )

        if old in content:
            content = content.replace(old, new)
            with open(INFER, "w") as f:
                f.write(content)
            print("infer.py: upgraded auto-push to pre-inject BEFORE SEG gen")
            patches_applied = True
        else:
            print("WARNING: Could not find old auto-push block for upgrade")

# Patch 5: Add /analyze endpoint for the AI Analysis pipeline
# Inserted BEFORE the /{model} catch-all route so FastAPI matches it first
ANALYZE_MARKER = "### ANALYZE_ENDPOINT ###"
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    # Remove old-style appended analyze block (without marker) to avoid duplicates
    old_analyze_marker = "# === ANALYZE ENDPOINT (AI Analysis Pipeline) ==="
    if old_analyze_marker in content:
        idx = content.find(old_analyze_marker)
        content = content[:idx].rstrip() + "\n"
        print("infer.py: removed old-style appended analyze block")

    if ANALYZE_MARKER not in content:
        insert_before = '@router.post("/{model}"'
        analyze_code = """

### ANALYZE_ENDPOINT ###
@router.post("/analyze")
async def analyze(request: dict):
    import json, tempfile, os, pathlib, hashlib, numpy as np, base64, io
    from pydicom import Dataset
    from pydicom.dataset import FileMetaDataset
    from pydicom.uid import generate_uid

    logger.info("Analyze Request: %s", request)

    image = request.get("image_uid") or request.get("image")
    if not image:
        raise HTTPException(status_code=400, detail="image_uid is required")
    study_uid = request.get("study_uid")
    if not study_uid:
        raise HTTPException(status_code=400, detail="study_uid is required")

    run_seg = request.get("run_segmentation", True)
    instance = app_instance()
    SEG_MODELS = ["optic_disc_cup", "vessel_seg", "lesion_seg"]

    # A SeriesInstanceUID alone is not sufficient for legacy data where the
    # same series UID can occur in multiple studies. Pin the datastore to the
    # study currently open in OHIF and invalidate the series-only cache.
    datastore = instance.datastore()
    if hasattr(datastore, "_study_id_hint"):
        datastore._study_id_hint = study_uid
    try:
        cache_image = os.path.realpath(
            os.path.join(datastore._datastore.image_path(), image)
        )
        cache_nifti = os.path.realpath(
            os.path.join(datastore._datastore.image_path(), f"{image}.nii.gz")
        )
        if os.path.isdir(cache_image):
            import shutil
            shutil.rmtree(cache_image, ignore_errors=True)
        if os.path.isfile(cache_nifti):
            os.unlink(cache_nifti)
        logger.info(
            "Analyze pinned to active study=%s series=%s",
            study_uid,
            image,
        )
    except Exception as cache_error:
        logger.warning("Could not clear study-specific analysis cache: %s", cache_error)

    labels = {}
    label_infos = {}
    if run_seg:
        for m in SEG_MODELS:
            try:
                r = instance.infer({"model": m, "image": image, "study_uid": study_uid, "result_extension": ".nrrd", "result_dtype": "uint8", "result_compress": False})
                f = r.get("file") or r.get("label")
                if f and os.path.exists(f):
                    labels[m] = f
                    li = r.get("params", {}).get("label_info")
                    if li:
                        label_infos[m] = li
                    logger.info("Segmentation %s -> %s", m, f)
            except Exception as e:
                logger.error("Segmentation %s failed: %s", m, e)

        if labels and request.get("push_dicom_seg", True):
            try:
                import requests, pathlib, hashlib
                from pydicom import dcmread
                from monailabel.datastore.utils.convert import nifti_to_dicom_seg

                image_uri = datastore.get_image_uri(image)
                image_path = next((image_uri.replace(s, "") for s in [".nii", ".nii.gz", ".nrrd"] if image_uri.endswith(s)), "")
                if image_path and os.path.isdir(image_path):
                    try:
                        dcm_files = list(pathlib.Path(image_path).glob("*"))
                        if dcm_files:
                            src_path = str(dcm_files[0])
                            src_ds = dcmread(src_path, stop_before_pixels=True)
                            needs_ipp = not hasattr(src_ds, 'ImagePositionPatient')
                            if not hasattr(src_ds, 'FrameOfReferenceUID') or needs_ipp:
                                src_full = dcmread(src_path)
                                if not hasattr(src_full, 'FrameOfReferenceUID'):
                                    src_full.FrameOfReferenceUID = "2.25." + str(int(hashlib.md5(str(src_full.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
                                if needs_ipp:
                                    src_full.ImagePositionPatient = [0, 0, 0]
                                    src_full.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                                    src_full.SliceThickness = 1.0
                                src_full.save_as(src_path)
                                with open(src_path, "rb") as fsrc:
                                    resp = requests.post("http://orthanc-container:8042/instances", data=fsrc, headers={"Content-Type": "application/dicom"})
                                logger.info(f"Analyze pre-injected geometry into source (resp={resp.status_code})")
                    except Exception as e2:
                        logger.warning(f"Analyze pre-inject geometry skipped: {e2}")

                    for m, res_img in labels.items():
                        label_info = label_infos.get(m)
                        if not label_info:
                            logger.warning("Analyze DICOM-SEG skipped for %s: missing label_info", m)
                            continue
                        try:
                            if isinstance(label_info, list) and label_info and isinstance(label_info[0], dict):
                                label_info[0]["model_name"] = m
                            dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                            if dicom_seg_file and os.path.exists(dicom_seg_file):
                                with open(dicom_seg_file, "rb") as fseg:
                                    resp = requests.post("http://orthanc-container:8042/instances", data=fseg, headers={"Content-Type": "application/dicom"})
                                    logger.info(f"Pushed DICOM-SEG to Orthanc from analyze/{m}: {resp.status_code}")
                                os.unlink(dicom_seg_file)
                        except Exception as e3:
                            logger.error("Analyze DICOM-SEG push failed for %s: %s", m, e3)
                else:
                    logger.warning("Analyze DICOM-SEG push skipped: source DICOM dir not found for %s", image)
            except Exception as e:
                logger.error("Analyze DICOM-SEG push failed: %s", e)

    optic = {"disc_area_px": 0, "cup_area_px": 0, "cup_disc_ratio": 0.0, "disc_center_x": None, "laterality": "UNKNOWN"}
    if "optic_disc_cup" in labels:
        try:
            import nrrd
            data, _ = nrrd.read(labels["optic_disc_cup"])
            if data.ndim == 3:
                data = data[0] if data.shape[0] == 1 else data.squeeze()
            disc = int(np.sum(data == 1))
            cup = int(np.sum(data == 2))
            ratio = cup / disc if disc > 0 else 0.0
            optic_mask = np.isin(data, (1, 2))
            # pynrrd preserves the NRRD (x, y) axis order, so axis 0 is horizontal.
            optic_columns = np.where(optic_mask)[0] if data.ndim == 2 else np.array([])
            disc_center_x = float(np.mean(optic_columns)) if optic_columns.size else None
            image_center_x = (data.shape[0] - 1) / 2 if data.ndim == 2 else None
            laterality = (
                "OS" if disc_center_x is not None and disc_center_x < image_center_x
                else "OD" if disc_center_x is not None
                else "UNKNOWN"
            )
            optic = {
                "disc_area_px": disc,
                "cup_area_px": cup,
                "cup_disc_ratio": round(ratio, 4),
                "disc_center_x": round(disc_center_x, 2) if disc_center_x is not None else None,
                "laterality": laterality,
            }
        except Exception as e:
            logger.error("Optic disc/cup quantification failed: %s", e)

    glaucoma = {"vcdr": 0.0, "risk": "N/A", "disc_area_px": 0, "cup_area_px": 0}
    if "optic_disc_cup" in labels:
        try:
            import nrrd
            data, _ = nrrd.read(labels["optic_disc_cup"])
            if data.ndim == 3:
                data = data[0] if data.shape[0] == 1 else data.squeeze()
            disc_mask = data == 1
            cup_mask = data == 2
            disc_area = int(np.sum(disc_mask))
            cup_area = int(np.sum(cup_mask))
            disc_rows = np.any(disc_mask, axis=1)
            cup_rows = np.any(cup_mask, axis=1)
            disc_h = np.max(np.where(disc_rows)) - np.min(np.where(disc_rows)) if disc_rows.any() else 0
            cup_h = np.max(np.where(cup_rows)) - np.min(np.where(cup_rows)) if cup_rows.any() else 0
            vcdr = cup_h / disc_h if disc_h > 0 else 0.0
            if vcdr < 0.3: risk = "Faible"
            elif vcdr < 0.5: risk = "Modere"
            elif vcdr < 0.7: risk = "Eleve"
            else: risk = "Tres eleve"
            glaucoma = {"vcdr": round(vcdr, 4), "risk": risk, "disc_area_px": disc_area, "cup_area_px": cup_area}
        except Exception as e:
            logger.error("Glaucoma quantification failed: %s", e)

    vessel = {"coverage_pct": 0.0, "pixel_count": 0}
    if "vessel_seg" in labels:
        import nrrd
        vessel_vol, _ = nrrd.read(labels["vessel_seg"])
    if "lesion_seg" in labels:
        import nrrd
        lesion_vol, _ = nrrd.read(labels["lesion_seg"])

    num_slices = 1
    if optic_vol is not None:
        if optic_vol.ndim == 4:
            num_slices = optic_vol.shape[1] if optic_vol.shape[0] == 1 else optic_vol.shape[0]
        elif optic_vol.ndim == 3:
            if optic_vol.shape[0] > 1:
                num_slices = optic_vol.shape[0]
            elif optic_vol.shape[0] == 1:
                num_slices = 1
            else:
                num_slices = 1

    # --- Per-slice quantification ---
    slice_results = []
    for i in range(num_slices):
        opt_sl = _extract_slice(optic_vol, i)
        ves_sl = _extract_slice(vessel_vol, i) if vessel_vol is not None else None
        les_sl = _extract_slice(lesion_vol, i) if lesion_vol is not None else None

        opt_metrics = {"disc_area_px": 0, "cup_area_px": 0, "cup_disc_ratio": 0.0, "disc_center_x": None, "laterality": "UNKNOWN"}
        gla_metrics = {"vcdr": 0.0, "risk": "N/A", "disc_area_px": 0, "cup_area_px": 0}
        ves_metrics = {"coverage_pct": 0.0, "pixel_count": 0}
        les_metrics = {
            "microaneurysms": 0, "hemorrhages": 0, "hard_exudates": 0,
            "soft_exudates": 0,
            "exudates": 0, "pixel_counts": {},
            "coverage_pct": 0.0,
        }

        if opt_sl is not None:
            try:
                opt_metrics = _process_optic_slice(opt_sl)
                gla_metrics = _process_glaucoma_slice(opt_sl)
            except Exception as e:
                logger.error("Per-slice optic/glaucoma quantification failed for slice %s: %s", i, e)

        if ves_sl is not None:
            try:
                total = int(ves_sl.size)
                v = int(np.sum(ves_sl > 0))
                ves_metrics = {"coverage_pct": round(v / total * 100, 2) if total > 0 else 0.0, "pixel_count": v}
            except Exception as e:
                logger.error("Vessel quantification failed for slice %s: %s", i, e)

        if les_sl is not None:
            try:
                import cv2
                total = int(les_sl.size)
                def _regions(class_id):
                    mask = np.ascontiguousarray(les_sl == class_id, dtype=np.uint8)
                    components, _ = cv2.connectedComponents(mask, connectivity=8)
                    return max(0, int(components) - 1)
                hard_exudates = _regions(3)
                soft_exudates = _regions(4)
                any_lesion = int(np.sum(les_sl > 0))
                les_metrics = {
                    "microaneurysms": _regions(1),
                    "hemorrhages": _regions(2),
                    "hard_exudates": hard_exudates,
                    "soft_exudates": soft_exudates,
                    "exudates": hard_exudates + soft_exudates,
                    "pixel_counts": {
                        "microaneurysms": int(np.sum(les_sl == 1)),
                        "hard_exudates": int(np.sum(les_sl == 3)),
                        "soft_exudates": int(np.sum(les_sl == 4)),
                        "hemorrhages": int(np.sum(les_sl == 2)),
                    },
                    "coverage_pct": round(any_lesion / total * 100, 2) if total > 0 else 0.0,
                    "model_id": "DDR-DeepLabV3Plus-EfficientNetB3",
                    "model_commit": "c09dbc164507872eb7c8b7f57c91b7ba4fdd289f",
                    "checkpoint_sha256": "f4c3c89a4da02b84af6cc85b4ee9cd4be35bf2c836cf230b0a6d06a3805b646b",
                }
            except Exception as e:
                logger.error("Lesion quantification failed for slice %s: %s", i, e)

        severity = _compute_severity(dr.get("grade", "Unknown"), gla_metrics["vcdr"])
        slice_results.append({
            "index": i,
            "optic_disc_cup": opt_metrics,
            "glaucoma": gla_metrics,
            "vessels": ves_metrics,
            "lesions": les_metrics,
            "severity_score": severity,
        })

    # --- Group by laterality, pick most critical per eye ---
    def _pick_critical(results, dr_info, gradcam, clahe):
        for r in results:
            r["dr_classification"] = dr_info
            r["gradcam_image"] = gradcam
            r["clahe_image"] = clahe
        return max(results, key=lambda r: r["severity_score"]) if results else None

    od_results = [r for r in slice_results if r["optic_disc_cup"]["laterality"] == "OD"]
    os_results = [r for r in slice_results if r["optic_disc_cup"]["laterality"] == "OS"]

    # --- Top-level backward-compatible metrics (use first slice) ---
    top_slice = slice_results[0] if slice_results else None
    optic = top_slice["optic_disc_cup"] if top_slice else {"disc_area_px": 0, "cup_area_px": 0, "cup_disc_ratio": 0.0, "disc_center_x": None, "laterality": "UNKNOWN"}
    glaucoma = top_slice["glaucoma"] if top_slice else {"vcdr": 0.0, "risk": "N/A", "disc_area_px": 0, "cup_area_px": 0}
    vessel = top_slice["vessels"] if top_slice else {"coverage_pct": 0.0, "pixel_count": 0}
    lesion = top_slice["lesions"] if top_slice else {
        "microaneurysms": 0, "hemorrhages": 0, "hard_exudates": 0,
        "soft_exudates": 0,
        "exudates": 0, "pixel_counts": {},
        "coverage_pct": 0.0,
    }

    # --- Grad-CAM / CLAHE ---
    gradcam_b64 = None
    clahe_b64 = None
    dr_task = instance._infers.get("dr_classification")
    if dr_task and hasattr(dr_task, "_hf_model") and dr_task._hf_model is not None:
        import sys; sys.path.insert(0, '/opt/monai/apps')
        from xai_utils import generate_gradcam, generate_clahe
        try:
            gradcam_b64 = generate_gradcam(image, instance, dr_task)
        except Exception as e:
            logger.warning("Grad-CAM unavailable: %s", str(e)[:200])
        try:
            clahe_b64 = generate_clahe(image, instance)
        except Exception as e:
            logger.warning("CLAHE unavailable: %s", str(e)[:200])

    # --- Pick most critical per eye ---
    critical_od = _pick_critical(od_results, dr, gradcam_b64, clahe_b64)
    critical_os = _pick_critical(os_results, dr, gradcam_b64, clahe_b64)

    report = {
        "source": {
            "study_instance_uid": study_uid,
            "series_instance_uid": image,
        },
        "dr_classification": dr,
        "lesions": lesion,
        "optic_disc_cup": optic,
        "glaucoma": glaucoma,
        "vessels": vessel,
        "gradcam_image": gradcam_b64,
        "clahe_image": clahe_b64,
        "per_instance": slice_results,
        "critical": {
            "od": critical_od,
            "os": critical_os,
        },
    }

    return report
"""
        idx = content.find(insert_before)
        if idx >= 0:
            content = content[:idx] + analyze_code + content[idx:]
            with open(INFER, "w") as f:
                f.write(content)
            print("infer.py: inserted enhanced /infer/analyze endpoint BEFORE /{model} catch-all")
            patches_applied = True
        else:
            print("WARNING: Could not find /{model} route in infer.py to insert analyze endpoint")

# Patch 23: Replace /infer/analyze with a single-instance-safe implementation.
# The old injected endpoint could delete the backend-prepared one-instance cache
# and referenced helper variables before assigning them.  Keep analyze small:
# run DR + masks against the current cache, compute metrics, and return report
# data without pushing extra DICOM-SEG objects.
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    start = content.find("### ANALYZE_ENDPOINT ###")
    end = content.find('@router.post("/{model}"', start)
    if start >= 0 and end > start:
        analyze_code = '''### ANALYZE_ENDPOINT ###
@router.post("/analyze")
async def analyze(request: dict):
    import os
    import numpy as np
    from fastapi import HTTPException

    logger.info("Analyze Request: %s", request)

    image = request.get("image_uid") or request.get("image")
    if not image:
        raise HTTPException(status_code=400, detail="image_uid is required")
    study_uid = request.get("study_uid")
    if not study_uid:
        raise HTTPException(status_code=400, detail="study_uid is required")

    source_sop_uid = request.get("source_sop_instance_uid")
    instance = app_instance()
    datastore = instance.datastore()
    if hasattr(datastore, "_study_id_hint"):
        datastore._study_id_hint = study_uid

    try:
        cache_dir = os.path.realpath(os.path.join(datastore._datastore.image_path(), image))
        cache_nifti = os.path.realpath(os.path.join(datastore._datastore.image_path(), f"{image}.nii.gz"))
        if os.path.isfile(cache_nifti):
            os.unlink(cache_nifti)
        if source_sop_uid:
            if not os.path.isdir(cache_dir):
                logger.warning("Analyze single-instance cache missing for series=%s sop=%s", image, source_sop_uid)
            logger.info("Analyze preserved single-instance cache for series=%s sop=%s", image, source_sop_uid)
        else:
            import shutil
            if os.path.isdir(cache_dir):
                shutil.rmtree(cache_dir, ignore_errors=True)
            logger.info("Analyze cleared series cache for study=%s series=%s", study_uid, image)
    except Exception as cache_error:
        logger.warning("Could not prepare analysis cache: %s", cache_error)

    def _read_label(path):
        import nrrd
        data, _ = nrrd.read(path)
        data = np.asarray(data)
        data = np.squeeze(data)
        while data.ndim > 2:
            data = data[0]
            data = np.squeeze(data)
        return data

    def _optic_metrics(data):
        if data is None:
            return {"disc_area_px": 0, "cup_area_px": 0, "cup_disc_ratio": 0.0, "disc_center_x": None, "laterality": "UNKNOWN"}
        disc = int(np.sum(data == 1))
        cup = int(np.sum(data == 2))
        ratio = cup / disc if disc > 0 else 0.0
        optic_mask = np.isin(data, (1, 2))
        columns = np.where(optic_mask)[0] if data.ndim == 2 else np.array([])
        disc_center_x = float(np.mean(columns)) if columns.size else None
        image_center_x = (data.shape[0] - 1) / 2 if data.ndim == 2 else None
        laterality = (
            "OS" if disc_center_x is not None and image_center_x is not None and disc_center_x < image_center_x
            else "OD" if disc_center_x is not None
            else "UNKNOWN"
        )
        return {
            "disc_area_px": disc,
            "cup_area_px": cup,
            "cup_disc_ratio": round(ratio, 4),
            "disc_center_x": round(disc_center_x, 2) if disc_center_x is not None else None,
            "laterality": laterality,
        }

    def _glaucoma_metrics(data):
        if data is None:
            return {"vcdr": 0.0, "risk": "N/A", "disc_area_px": 0, "cup_area_px": 0}
        disc_mask = data == 1
        cup_mask = data == 2
        disc_area = int(np.sum(disc_mask))
        cup_area = int(np.sum(cup_mask))
        disc_rows = np.any(disc_mask, axis=1) if data.ndim == 2 else np.array([])
        cup_rows = np.any(cup_mask, axis=1) if data.ndim == 2 else np.array([])
        disc_h = np.max(np.where(disc_rows)) - np.min(np.where(disc_rows)) if disc_rows.any() else 0
        cup_h = np.max(np.where(cup_rows)) - np.min(np.where(cup_rows)) if cup_rows.any() else 0
        vcdr = cup_h / disc_h if disc_h > 0 else 0.0
        if vcdr < 0.3:
            risk = "Faible"
        elif vcdr < 0.5:
            risk = "Modere"
        elif vcdr < 0.7:
            risk = "Eleve"
        else:
            risk = "Tres eleve"
        return {"vcdr": round(vcdr, 4), "risk": risk, "disc_area_px": disc_area, "cup_area_px": cup_area}

    def _vessel_metrics(data):
        if data is None:
            return {"coverage_pct": 0.0, "pixel_count": 0}
        total = int(data.size)
        count = int(np.sum(data > 0))
        return {"coverage_pct": round(count / total * 100, 2) if total else 0.0, "pixel_count": count}

    def _lesion_metrics(data):
        if data is None:
            return {
                "microaneurysms": 0, "hemorrhages": 0, "hard_exudates": 0,
                "soft_exudates": 0,
                "exudates": 0, "pixel_counts": {},
                "coverage_pct": 0.0,
            }
        import cv2
        total = int(data.size)
        any_lesion = int(np.sum(data > 0))
        def _regions(class_id):
            mask = np.ascontiguousarray(data == class_id, dtype=np.uint8)
            components, _ = cv2.connectedComponents(mask, connectivity=8)
            return max(0, int(components) - 1)
        hard_exudates = _regions(2)
        soft_exudates = _regions(4)
        return {
            "microaneurysms": _regions(1),
            "hemorrhages": _regions(2),
            "hard_exudates": hard_exudates,
            "soft_exudates": soft_exudates,
            "exudates": hard_exudates + soft_exudates,
            "pixel_counts": {
                "microaneurysms": int(np.sum(data == 1)),
                "hard_exudates": int(np.sum(data == 3)),
                "soft_exudates": int(np.sum(data == 4)),
                "hemorrhages": int(np.sum(data == 2)),
            },
            "coverage_pct": round(any_lesion / total * 100, 2) if total else 0.0,
            "model_id": "DDR-DeepLabV3Plus-EfficientNetB3",
            "model_commit": "c09dbc164507872eb7c8b7f57c91b7ba4fdd289f",
            "checkpoint_sha256": "f4c3c89a4da02b84af6cc85b4ee9cd4be35bf2c836cf230b0a6d06a3805b646b",
        }

    def _severity(dr_info, glaucoma):
        grade = str(dr_info.get("grade") or dr_info.get("label") or "Unknown").lower()
        dr_score = 0
        for key, score in (("proliferative", 4), ("severe", 3), ("moderate", 2), ("mild", 1)):
            if key in grade:
                dr_score = score
                break
        return dr_score * 10 + float(glaucoma.get("vcdr") or 0)

    def _normalize_dr(params):
        raw_grade = params.get("dr_label") or params.get("label") or params.get("prediction") or "Unknown"
        confidence = params.get("dr_probability") or params.get("probability") or params.get("confidence") or 0.0
        probabilities = params.get("dr_all_probabilities") or params.get("probabilities") or {}
        if isinstance(raw_grade, list):
            scored = [item for item in raw_grade if isinstance(item, dict)]
            if scored:
                best = max(scored, key=lambda item: float(item.get("score") or 0.0))
                raw_grade = best.get("label") or best.get("name") or str(best.get("idx") or "Unknown")
                confidence = float(best.get("score") or 0.0)
                probabilities = {
                    str(item.get("label") or item.get("name") or item.get("idx")): float(item.get("score") or 0.0)
                    for item in scored
                }
        dr_info = {
            "grade": str(raw_grade),
            "confidence": float(confidence or 0.0),
            "probabilities": probabilities,
        }
        if "dr_grade" in params and params.get("dr_grade") is not None:
            dr_info["grade_index"] = int(params["dr_grade"])
        else:
            normalized_grade = str(raw_grade).strip().lower().replace("_", " ")
            dr_info["grade_index"] = next(
                (
                    index
                    for marker, index in (
                        ("proliferative", 4), ("severe", 3), ("moderate", 2),
                        ("mild", 1), ("no dr", 0), ("normal", 0),
                    )
                    if marker in normalized_grade
                ),
                None,
            )
        for key in (
            "status", "model_id", "model_commit", "backbone", "backbone_revision",
            "checkpoint_name", "checkpoint_sha256",
            "calibration_status", "temperature", "preprocessing_version",
            "inference_time_ms", "device",
        ):
            if key in params:
                dr_info[key] = params[key]
        return dr_info

    def _run_model(model, extra=None):
        req = {
            "model": model,
            "image": image,
            "study_uid": study_uid,
            "result_extension": ".nrrd",
            "result_dtype": "uint8",
            "result_compress": False,
        }
        if source_sop_uid:
            req["source_sop_instance_uid"] = source_sop_uid
        if extra:
            req.update(extra)
        return instance.infer(req)

    labels = {}
    for model in ("optic_disc_cup", "vessel_seg", "lesion_seg"):
        try:
            result = _run_model(model)
            path = result.get("file") or result.get("label")
            if path and os.path.exists(path):
                labels[model] = path
                logger.info("Analyze segmentation %s -> %s", model, path)
            else:
                logger.warning("Analyze segmentation %s returned no label file", model)
        except Exception as e:
            logger.error("Analyze segmentation %s failed: %s", model, e)

    clip_dr = {
        "status": "unavailable",
        "grade": "Unknown",
        "confidence": 0.0,
        "probabilities": {},
        "calibration_status": "not_locally_calibrated",
    }
    try:
        clip_result = _run_model(
            "clip_dr_classification",
            {"result_extension": ".json", "device": "cpu"},
        )
        clip_dr = _normalize_dr(clip_result.get("params") or {})
        clip_dr.setdefault("status", "ok")
        clip_dr.setdefault("calibration_status", "not_locally_calibrated")
    except Exception as e:
        logger.warning("Analyze CLIP-DR unavailable: %s", e)
        message = str(e)
        clip_dr["reason"] = (
            "checkpoint CLIP-DR APTOS non installé"
            if isinstance(e, FileNotFoundError) or "not installed" in message.lower()
            or "non installé" in message.lower()
            else message[:240]
        )

    dr = clip_dr
    dr_classification_models = {"clip_dr": clip_dr}

    fovea = None
    try:
        fovea_result = _run_model("fovea_detection", {"result_extension": ".json"})
        fovea_params = fovea_result.get("params") or fovea_result
        fovea = fovea_params.get("fovea")
        if not fovea:
            logger.warning("Analyze fovea detection returned no coordinates")
    except Exception as e:
        logger.error("Analyze fovea detection failed: %s", e)

    optic_data = vessel_data = lesion_data = None
    try:
        optic_data = _read_label(labels["optic_disc_cup"]) if "optic_disc_cup" in labels else None
    except Exception as e:
        logger.error("Analyze optic label read failed: %s", e)
    try:
        vessel_data = _read_label(labels["vessel_seg"]) if "vessel_seg" in labels else None
    except Exception as e:
        logger.error("Analyze vessel label read failed: %s", e)
    try:
        lesion_data = _read_label(labels["lesion_seg"]) if "lesion_seg" in labels else None
    except Exception as e:
        logger.error("Analyze lesion label read failed: %s", e)

    optic = _optic_metrics(optic_data)
    glaucoma = _glaucoma_metrics(optic_data)
    vessels = _vessel_metrics(vessel_data)
    lesions = _lesion_metrics(lesion_data)

    def _normalize_uint8(arr):
        arr = np.asarray(arr)
        arr = np.nan_to_num(arr.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        lo = float(np.percentile(arr, 1))
        hi = float(np.percentile(arr, 99))
        if hi <= lo:
            hi = float(arr.max()) if arr.size else 1.0
            lo = float(arr.min()) if arr.size else 0.0
        if hi <= lo:
            return np.zeros(arr.shape, dtype=np.uint8)
        arr = np.clip((arr - lo) / (hi - lo), 0, 1)
        return (arr * 255).astype(np.uint8)

    def _read_source_rgb():
        try:
            import pathlib
            from pydicom import dcmread
            files = list(pathlib.Path(cache_dir).glob("*")) if os.path.isdir(cache_dir) else []
            if not files:
                return None
            selected = None
            for file_path in files:
                try:
                    ds = dcmread(str(file_path))
                    if not source_sop_uid or str(getattr(ds, "SOPInstanceUID", "")) == str(source_sop_uid):
                        selected = ds
                        break
                except Exception:
                    continue
            if selected is None:
                selected = dcmread(str(files[0]))
            arr = selected.pixel_array
            arr = np.squeeze(arr)
            while arr.ndim > 3:
                arr = arr[0]
                arr = np.squeeze(arr)
            if arr.ndim == 2:
                gray = _normalize_uint8(arr)
                if str(getattr(selected, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
                    gray = 255 - gray
                rgb = np.stack([gray, gray, gray], axis=-1)
            else:
                if arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
                    arr = np.moveaxis(arr, 0, -1)
                rgb = _normalize_uint8(arr[..., :3])
            return rgb
        except Exception as e:
            logger.warning("Explainability source image unavailable: %s", e)
            return None

    def _resize_for_payload(rgb, max_side=640):
        try:
            import cv2
            h, w = rgb.shape[:2]
            scale = min(1.0, float(max_side) / float(max(h, w)))
            if scale < 1.0:
                return cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        except Exception:
            pass
        return rgb

    def _png_b64(rgb):
        try:
            import base64
            import cv2
            ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            return base64.b64encode(encoded.tobytes()).decode("ascii") if ok else None
        except Exception as e:
            logger.warning("PNG encoding failed: %s", e)
            return None

    def _make_clahe(rgb):
        try:
            import cv2
            lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
            l_chan, a_chan, b_chan = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = cv2.merge([clahe.apply(l_chan), a_chan, b_chan])
            return cv2.cvtColor(enhanced, cv2.COLOR_LAB2RGB)
        except Exception as e:
            logger.warning("CLAHE generation failed: %s", e)
            return None

    def _make_attention_overlay(rgb):
        try:
            import cv2
            import torch
            from PIL import Image
            dr_task = instance._infers.get("dr_classification")
            processor = getattr(dr_task, "_hf_processor", None)
            model = getattr(dr_task, "_hf_model", None)
            if processor is None or model is None:
                return None
            try:
                if hasattr(model, "set_attn_implementation"):
                    model.set_attn_implementation("eager")
                elif hasattr(model, "config"):
                    model.config._attn_implementation = "eager"
            except Exception as e:
                logger.warning("Could not switch attention implementation: %s", e)
            device = next(model.parameters()).device
            pil_image = Image.fromarray(rgb)
            inputs = processor(images=pil_image, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = model(**inputs, output_attentions=True)
            attentions = getattr(outputs, "attentions", None)
            if not attentions:
                return None
            cls_attention = attentions[-1][0].mean(dim=0)[0, 1:].detach().float().cpu().numpy()
            grid = int(np.sqrt(cls_attention.size))
            if grid * grid != cls_attention.size:
                return None
            heat = cls_attention.reshape(grid, grid)
            heat = heat - heat.min()
            if heat.max() > 0:
                heat = heat / heat.max()
            heat = cv2.resize(heat, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_CUBIC)
            heat_u8 = np.uint8(np.clip(heat, 0, 1) * 255)
            color = cv2.applyColorMap(heat_u8, cv2.COLORMAP_JET)
            color = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
            return cv2.addWeighted(rgb, 0.58, color, 0.42, 0)
        except Exception as e:
            logger.warning("Attention heatmap generation failed: %s", e)
            return None

    source_rgb = _read_source_rgb()
    clahe_image = None
    gradcam_image = None
    if source_rgb is not None:
        payload_rgb = _resize_for_payload(source_rgb)
        clahe_rgb = _make_clahe(payload_rgb)
        overlay_rgb = _make_attention_overlay(payload_rgb)
        clahe_image = _png_b64(clahe_rgb) if clahe_rgb is not None else None
        gradcam_image = _png_b64(overlay_rgb) if overlay_rgb is not None else None

    slice_result = {
        "index": 0,
        "source_sop_instance_uid": source_sop_uid,
        "dr_classification": dr,
        "dr_classification_models": dr_classification_models,
        "optic_disc_cup": optic,
        "glaucoma": glaucoma,
        "vessels": vessels,
        "lesions": lesions,
        "fovea": fovea,
        "severity_score": _severity(dr, glaucoma),
        "gradcam_image": gradcam_image,
        "clahe_image": clahe_image,
    }

    return {
        "source": {
            "study_instance_uid": study_uid,
            "series_instance_uid": image,
            "source_sop_instance_uid": source_sop_uid,
        },
        "dr_classification": dr,
        "dr_classification_models": dr_classification_models,
        "lesions": lesions,
        "optic_disc_cup": optic,
        "glaucoma": glaucoma,
        "vessels": vessels,
        "fovea": fovea,
        "gradcam_image": gradcam_image,
        "clahe_image": clahe_image,
        "per_instance": [slice_result],
        "critical": {
            "od": slice_result if optic.get("laterality") == "OD" else None,
            "os": slice_result if optic.get("laterality") == "OS" else None,
        },
    }

'''
        content = content[:start] + analyze_code + content[end:]
        with open(INFER, "w") as f:
            f.write(content)
        print("infer.py: replaced /infer/analyze with single-instance-safe endpoint")
        patches_applied = True
    else:
        print("WARNING: Could not find analyze endpoint boundaries for Patch 23")

# Patch 6: Fix series_dir to use DICOM directory instead of NIfTI path for SEG generation
# Also ensures DICOM files are downloaded first via get_image_uri
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    old = '''                image_path = os.path.realpath(os.path.join(instance.datastore()._datastore.image_path(), image))
                if not os.path.isdir(image_path):
                    image_uri = instance.datastore().get_image_uri(image)
                    image_path = next((image_uri.replace(s, "") for s in [".nii", ".nii.gz", ".nrrd"] if image_uri.endswith(s)), "")
                if image_path and os.path.isdir(image_path):'''
    new = '''                image_uri = instance.datastore().get_image_uri(image)
                image_dir = os.path.realpath(os.path.join(instance.datastore()._datastore.image_path(), image))
                if not os.path.isdir(image_dir):
                    image_dir = next((image_uri.replace(s, "") for s in [".nii", ".nii.gz", ".nrrd"] if image_uri.endswith(s)), "")
                image_path = image_dir
                if image_path and os.path.isdir(image_path):'''
    if old in content and 'image_uri = instance.datastore().get_image_uri(image)' not in content[:600]:
        content = content.replace(old, new)
        with open(INFER, "w") as f:
            f.write(content)
        print("infer.py: fixed series_dir to use DICOM directory (calls get_image_uri first)")
        patches_applied = True

# Patch 7: Inject correct StudyInstanceUID from source DICOMs into generated SEG
# Must run AFTER Patch 6 (which ensures DICOM files are downloaded)
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    old = '''                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:'''
    new = '''                    # Read study_uid from frontend params, inject into source DICOMs BEFORE SEG gen.
                    # NOTE: We do NOT inject patient_id here — the frontend sends a random
                    # synthetic PatientID that differs from the actual DICOM PatientID, which
                    # would cause OHIF to show "Multiple Patients" for the same study.
                    source_study_uid = p.get("study_uid") or result.get("params", {}).get("study_uid")
                    if not source_study_uid:
                        try:
                            dcm_files = list(pathlib.Path(image_path).glob("*"))
                            if dcm_files:
                                src_ds = dcmread(str(dcm_files[0]), stop_before_pixels=True)
                                if hasattr(src_ds, 'StudyInstanceUID'):
                                    source_study_uid = str(src_ds.StudyInstanceUID)
                        except Exception as e:
                            logger.warning(f"Could not read source StudyInstanceUID: {e}")

                    # Inject study_uid into source DICOMs BEFORE SEG gen so highdicom inherits them
                    if source_study_uid:
                        try:
                            dcm_files = list(pathlib.Path(image_path).glob("*"))
                            for fpath in dcm_files:
                                ds = dcmread(str(fpath))
                                if str(ds.StudyInstanceUID) != source_study_uid:
                                    ds.StudyInstanceUID = source_study_uid
                                    ds.save_as(str(fpath))
                                    logger.info(f"Injected StudyInstanceUID into source: {fpath.name}")
                        except Exception as e:
                            logger.warning(f"Could not inject StudyInstanceUID into sources: {e}")
                        logger.info(f"Source StudyInstanceUID: {source_study_uid}")

                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:'''
    if old in content:
        content = content.replace(old, new)
        with open(INFER, "w") as f:
            f.write(content)
        print("infer.py: StudyInstanceUID injected into source DICOMs BEFORE SEG gen (NOT patient_id)")
        patches_applied = True
    else:
        # Patch 7B: If infer.py already has the OLD patient_id injection code (from a previous
        # patch run), replace it with the corrected version that does NOT inject patient_id.
        _p7b_old = '''                    source_study_uid = p.get("study_uid") or result.get("params", {}).get("study_uid")
                    source_patient_id = p.get("patient_id") or result.get("params", {}).get("patient_id")
                    if not source_study_uid:
                        try:
                            dcm_files = list(pathlib.Path(image_path).glob("*"))
                            if dcm_files:
                                src_ds = dcmread(str(dcm_files[0]), stop_before_pixels=True)
                                if hasattr(src_ds, 'StudyInstanceUID'):
                                    source_study_uid = str(src_ds.StudyInstanceUID)
                        except Exception as e:
                            logger.warning(f"Could not read source StudyInstanceUID: {e}")

                    # Inject study_uid + patient_id into source DICOMs BEFORE SEG gen so highdicom inherits them
                    if source_study_uid or source_patient_id:
                        try:
                            dcm_files = list(pathlib.Path(image_path).glob("*"))
                            for fpath in dcm_files:
                                ds = dcmread(str(fpath))
                                modified = False
                                if source_study_uid and str(ds.StudyInstanceUID) != source_study_uid:
                                    ds.StudyInstanceUID = source_study_uid
                                    modified = True
                                if source_patient_id and hasattr(ds, 'PatientID') and str(ds.PatientID) != source_patient_id:
                                    ds.PatientID = source_patient_id
                                    modified = True
                                if modified:
                                    ds.save_as(str(fpath))
                                    logger.info(f"Injected tags into source: {fpath.name}")
                        except Exception as e:
                            logger.warning(f"Could not inject tags into sources: {e}")
                    if source_study_uid:
                        logger.info(f"Source StudyInstanceUID: {source_study_uid}")
                    if source_patient_id:
                        logger.info(f"Source PatientID: {source_patient_id}")

                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:'''
        _p7b_new = '''                    # Read study_uid from frontend params, inject into source DICOMs BEFORE SEG gen.
                    # NOTE: We do NOT inject patient_id here — the frontend sends a random
                    # synthetic PatientID that differs from the actual DICOM PatientID, which
                    # would cause OHIF to show "Multiple Patients" for the same study.
                    source_study_uid = p.get("study_uid") or result.get("params", {}).get("study_uid")
                    if not source_study_uid:
                        try:
                            dcm_files = list(pathlib.Path(image_path).glob("*"))
                            if dcm_files:
                                src_ds = dcmread(str(dcm_files[0]), stop_before_pixels=True)
                                if hasattr(src_ds, 'StudyInstanceUID'):
                                    source_study_uid = str(src_ds.StudyInstanceUID)
                        except Exception as e:
                            logger.warning(f"Could not read source StudyInstanceUID: {e}")

                    # Inject study_uid into source DICOMs BEFORE SEG gen so highdicom inherits them
                    if source_study_uid:
                        try:
                            dcm_files = list(pathlib.Path(image_path).glob("*"))
                            for fpath in dcm_files:
                                ds = dcmread(str(fpath))
                                if str(ds.StudyInstanceUID) != source_study_uid:
                                    ds.StudyInstanceUID = source_study_uid
                                    ds.save_as(str(fpath))
                                    logger.info(f"Injected StudyInstanceUID into source: {fpath.name}")
                        except Exception as e:
                            logger.warning(f"Could not inject StudyInstanceUID into sources: {e}")
                        logger.info(f"Source StudyInstanceUID: {source_study_uid}")

                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:'''
        if _p7b_old in content:
            content = content.replace(_p7b_old, _p7b_new)
            with open(INFER, "w") as f:
                f.write(content)
            print("infer.py: REMOVED patient_id injection from source DICOMs (kept StudyInstanceUID only)")
            patches_applied = True


# Patch 8: Fix DICOM SEG for OHIF — BINARY type + geometry injection + StudyUID post-processing
# Target: _highdicom_nifti_to_dicom_seg() inside the installed convert.py
OHIF_SEG_MARKER = "### OHIF_SEG_COMPAT ###"
if os.path.exists(CONVERT):
    with open(CONVERT) as f:
        content = f.read()

    if OHIF_SEG_MARKER not in content:
        _p8_changed = False

        # ── Fix A: Geometry injection + BINARY pixel_array ──────────────────────
        # Replace the hd.seg.Segmentation() call that uses LABELMAP with one that:
        #   1. Injects geometry into all source datasets in-memory
        #   2. Builds a 4D BINARY one-hot mask (D, H, W, n_segs)
        #   3. Uses BINARY segmentation type for broad OHIF/Cornerstone3D support
        old_seg_labelmap = '''    seg = hd.seg.Segmentation(
        source_images=image_datasets,
        pixel_array=seg_array,
        segmentation_type=hd.seg.SegmentationTypeValues.LABELMAP,'''
        new_seg_binary = '''    ### OHIF_SEG_COMPAT ###
    # Inject geometry into ALL source datasets lacking spatial tags (fundus/OP images)
    # Use a single FrameOfReferenceUID for the entire series (derived from first SOP UID)
    import hashlib as _hl
    _fruid_8a = None
    for _si, _sd in enumerate(image_datasets):
        if _fruid_8a is None and hasattr(_sd, "SOPInstanceUID"):
            _fruid_8a = "2.25." + str(int(_hl.md5(str(_sd.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
        if not hasattr(_sd, "FrameOfReferenceUID"):
            _sd.FrameOfReferenceUID = _fruid_8a
        if not hasattr(_sd, "ImagePositionPatient"):
            _sd.ImagePositionPatient = [0.0, 0.0, float(_si)]
            _sd.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
            _sd.SliceThickness = 1.0
            _sd.SpacingBetweenSlices = 1.0
    # Build BINARY one-hot masks (D, H, W, n_segs) for OHIF compatibility
    _nsegs = len(segment_descriptions)
    _sa = seg_array if seg_array.ndim == 3 else seg_array[np.newaxis]
    _bin = np.stack([(_sa == s + 1).astype(np.uint8) for s in range(_nsegs)], axis=-1)
    seg = hd.seg.Segmentation(
        source_images=image_datasets,
        pixel_array=_bin,
        segmentation_type=hd.seg.SegmentationTypeValues.BINARY,'''

        if old_seg_labelmap in content:
            content = content.replace(old_seg_labelmap, new_seg_binary)
            _p8_changed = True
            print("convert.py Patch 8A: LABELMAP→BINARY + geometry injection applied")
        else:
            # Fallback: at least inject the marker and switch type alone
            if "SegmentationTypeValues.LABELMAP" in content:
                content = content.replace(
                    "SegmentationTypeValues.LABELMAP",
                    "SegmentationTypeValues.BINARY  ### OHIF_SEG_COMPAT ###"
                )
                _p8_changed = True
                print("convert.py Patch 8A (fallback): LABELMAP→BINARY only")
            else:
                # Already patched or BINARY already in use; add marker so we skip next run
                print("WARNING: Patch 8A — LABELMAP pattern not found (already BINARY or different version)")

        # ── Fix B: Post-process SEG to enforce StudyInstanceUID from source ──────
        old_save_return = '''    seg.save_as(output_file)
    logger.info(f"DICOM SEG saved to: {output_file}")

    return output_file'''
        new_save_return = '''    seg.save_as(output_file)
    logger.info(f"DICOM SEG saved to: {output_file}")

    # OHIF fix: enforce StudyInstanceUID + ReferencedSeriesSequence + PerFrame ReferencedSOPInstanceUID from source images
    try:
        if image_datasets:
            _st = str(image_datasets[0].StudyInstanceUID) if hasattr(image_datasets[0], "StudyInstanceUID") else None
            _sr = str(image_datasets[0].SeriesInstanceUID) if hasattr(image_datasets[0], "SeriesInstanceUID") else None
            _p10_sop_list = [str(ds.SOPInstanceUID) for ds in image_datasets if hasattr(ds, "SOPInstanceUID")]
            if _st or _sr or _p10_sop_list:
                from pydicom import dcmread as _dr
                _seg_fix = _dr(output_file)
                _mod_fix = False
                if _st and str(_seg_fix.StudyInstanceUID) != _st:
                    _seg_fix.StudyInstanceUID = _st
                    _mod_fix = True
                    logger.info(f"Fixed SEG StudyInstanceUID: {_st}")
                if _sr and hasattr(_seg_fix, "ReferencedSeriesSequence"):
                    for _rs in _seg_fix.ReferencedSeriesSequence:
                        if hasattr(_rs, "SeriesInstanceUID") and str(_rs.SeriesInstanceUID) != _sr:
                            _rs.SeriesInstanceUID = _sr
                            _mod_fix = True
                            logger.info(f"Fixed SEG ReferencedSeriesSequence SeriesUID: {_sr}")
                # Fix ReferencedSOPInstanceUID: brute-force recursive walker that finds
                # EVERY ReferencedSOPInstanceUID regardless of DICOM path structure and
                # always sets it to the correct source SOP UID by frame index.
                if _p10_sop_list:
                    # Validate frame count
                    if hasattr(_seg_fix, "PerFrameFunctionalGroupsSequence"):
                        _nf = len(_seg_fix.PerFrameFunctionalGroupsSequence)
                        _ns = len(_p10_sop_list)
                        if _nf != _ns:
                            logger.warning(
                                f"Frame count mismatch: SEG has {_nf} frames "
                                f"but source has {_ns} images"
                            )

                    def _force_fix_sop_refs(_item, _frame_idx, _sop_list):
                        _expected = _sop_list[_frame_idx] if _frame_idx < len(_sop_list) else _sop_list[0]
                        _count = 0
                        for _elem in _item:
                            if _elem.keyword == "ReferencedSOPInstanceUID":
                                _old_val = str(_elem.value)
                                if _old_val != _expected:
                                    _elem.value = _expected
                                    _count += 1
                                    logger.info(
                                        f"SEG Frame {_frame_idx}: Forced ReferencedSOPInstanceUID "
                                        f"{_old_val[:60]}... -> {_expected[:60]}..."
                                    )
                                else:
                                    _count += 1
                            elif _elem.VR == "SQ" and _elem.value is not None:
                                for _sub_item in _elem.value:
                                    _count += _force_fix_sop_refs(_sub_item, _frame_idx, _sop_list)
                        return _count

                    _total_fixes = 0
                    if hasattr(_seg_fix, "PerFrameFunctionalGroupsSequence"):
                        for _p10_fi, _p10_fg in enumerate(_seg_fix.PerFrameFunctionalGroupsSequence):
                            _total_fixes += _force_fix_sop_refs(_p10_fg, _p10_fi, _p10_sop_list)

                    if hasattr(_seg_fix, "SharedFunctionalGroupsSequence"):
                        for _sfg in _seg_fix.SharedFunctionalGroupsSequence:
                            for _sfi in range(len(_p10_sop_list)):
                                _total_fixes += _force_fix_sop_refs(_sfg, _sfi, _p10_sop_list)

                    if _total_fixes > 0:
                        _mod_fix = True
                        logger.info(f"SEG: Fixed {_total_fixes} ReferencedSOPInstanceUID references")
                if _mod_fix:
                    _seg_fix.save_as(output_file)
                    logger.info("SEG re-saved with corrected study/series/SOP UIDs")
    except Exception as _pe:
        logger.warning(f"SEG UID post-processing skipped: {_pe}")

    return output_file'''

        if old_save_return in content:
            content = content.replace(old_save_return, new_save_return)
            _p8_changed = True
            print("convert.py Patch 8B: StudyUID/SOPUID post-processing added")
        else:
            print("WARNING: Patch 8B — seg.save_as block not found (pattern mismatch?)")

        if _p8_changed:
            with open(CONVERT, "w") as f:
                f.write(content)
            print("convert.py: OHIF SEG compatibility fixes applied (Patch 8/10)")
            patches_applied = True
    else:
        patches_applied = True  # Patch 8 already applied

# Patch 10: Add Django webhook call after each Orthanc push to notify the worklist
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    marker_django = "### MONAI_DJANGO_WEBHOOK ###"
    if marker_django not in content:
        # Replace Orthanc push calls to also notify Django worklist
        old_push = '''                    resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")'''
        new_push = '''                    resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")
                            # Notify Django worklist
                            try:
                                import json as _dj_json
                                _dj_body = _dj_json.dumps({"study_instance_uid": str(source_study_uid or ""), "status": "AI_ANALYZED"})
                                _dj_resp = requests.post("http://backend:8001/api/exams/monai-webhook/", data=_dj_body, headers={"Content-Type": "application/json"}, timeout=10)
                                logger.info(f"Notified Django worklist: {_dj_resp.status_code}")
                            except Exception as _dj_e:
                                logger.warning(f"Failed to notify Django worklist: {_dj_e}")
                        ### MONAI_DJANGO_WEBHOOK ###'''

        if old_push in content:
            content = content.replace(old_push, new_push)
            with open(INFER, "w") as f:
                f.write(content)
            print("infer.py Patch 10: Django worklist webhook added after Orthanc push")
            patches_applied = True
        else:
            # Try the alternative push pattern (from Patch 3/7 auto-push)
            old_push2 = '''                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")'''
            new_push2 = '''                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")
                            # Notify Django worklist
                            try:
                                import json as _dj_json
                                _dj_body = _dj_json.dumps({"study_instance_uid": str(source_study_uid or ""), "status": "AI_ANALYZED"})
                                _dj_resp = requests.post("http://backend:8001/api/exams/monai-webhook/", data=_dj_body, headers={"Content-Type": "application/json"}, timeout=10)
                                logger.info(f"Notified Django worklist: {_dj_resp.status_code}")
                            except Exception as _dj_e:
                                logger.warning(f"Failed to notify Django worklist: {_dj_e}")
                        ### MONAI_DJANGO_WEBHOOK ###'''
            if old_push2 in content:
                content = content.replace(old_push2, new_push2)
                with open(INFER, "w") as f:
                    f.write(content)
                print("infer.py Patch 10: Django worklist webhook added after Orthanc push (alt)")
                patches_applied = True
            else:
                print("WARNING: Patch 10 — Orthanc push pattern not found in infer.py")
    else:
        patches_applied = True  # Patch 10 already applied

# Patch 11: Append brute-force ReferencedSOPInstanceUID fix in the WRAPPER function
# nifti_to_dicom_seg(), right before the final latency log.  This runs after BOTH
# the ITK and highdicom paths, reads the SEG output, and forces ALL
# ReferencedSOPInstanceUID values to match the ACTUAL SOPInstanceUID from the
# source DICOM file on disk (not the directory name / request UID).  This fixes
# the "No imageId found for SOPInstanceUID" error when the DICOM file on disk
# has a different SOPInstanceUID than what OHIF expects.
PATCH11_CONVERT = "/usr/local/lib/python3.10/dist-packages/monailabel/datastore/utils/convert.py"
PATCH11_MARKER = "### OHIF_PATCH_11_FORCE_SOP ###"

# The old-style code block (file-read + dirname fallback) that needs upgrading:
PATCH11_OLD_CODE_BLOCK = """            # Discover the actual SOPInstanceUID from source DICOM files on disk
            _p11_src_dir = _p11_pl.Path(series_dir)
            _p11_dcm_files = sorted(_p11_src_dir.glob("*.dcm"))
            _p11_expected = None
            if _p11_dcm_files:
                _p11_src = _p11_dr(str(_p11_dcm_files[0]), stop_before_pixels=True)
                if hasattr(_p11_src, "SOPInstanceUID"):
                    _p11_expected = str(_p11_src.SOPInstanceUID)
                    logger.info(f"Patch 11: Source SOPInstanceUID from file: {_p11_expected}")

            if _p11_expected is None:
                _p11_expected = _p11_pl.Path(series_dir).name
                logger.warning(f"Patch 11: Falling back to series_dir name: {_p11_expected}")"""
# The new Orthanc-querying code (with file fallback) to replace the old block.
# Fixed to read StudyInstanceUID from source DICOM file (NOT from parent dir hash).
PATCH11_NEW_ORTHANC = """            # Query Orthanc for the actual SOPInstanceUID in this series.
            # The cache file's SOPInstanceUID may be stale (different from Orthanc).
            import urllib.request as _p11_urlreq
            import json as _p11_json
            _p11_expected = None
            _p11_series_uid = _p11_pl.Path(series_dir).name
            # Read both SOPInstanceUID and StudyInstanceUID from cached source DICOM
            _p11_src_dir = _p11_pl.Path(series_dir)
            _p11_dcm_files = sorted(_p11_src_dir.glob("*.dcm"))
            _p11_file_sop = None
            _p11_study_uid = None
            if _p11_dcm_files:
                _p11_src = _p11_dr(str(_p11_dcm_files[0]), stop_before_pixels=True)
                if hasattr(_p11_src, "SOPInstanceUID"):
                    _p11_file_sop = str(_p11_src.SOPInstanceUID)
                if hasattr(_p11_src, "StudyInstanceUID"):
                    _p11_study_uid = str(_p11_src.StudyInstanceUID)
            try:
                if _p11_study_uid:
                    # Query Orthanc at instance level with BOTH Study+Series UIDs for precise filtering
                    _p11_q = _p11_json.dumps({"Level": "instance", "Query": {"StudyInstanceUID": _p11_study_uid, "SeriesInstanceUID": _p11_series_uid}}).encode()
                    _p11_req = _p11_urlreq.Request("http://orthanc-container:8042/tools/find", data=_p11_q, headers={"Content-Type": "application/json"})
                    _p11_resp = _p11_urlreq.urlopen(_p11_req, timeout=10)
                    _p11_data = _p11_json.loads(_p11_resp.read())
                    if isinstance(_p11_data, dict):
                        _p11_first_key = next(iter(_p11_data), None)
                        if _p11_first_key is not None:
                            _p11_entry = _p11_data[_p11_first_key]
                            if isinstance(_p11_entry, dict):
                                _p11_expected = _p11_entry.get("MainDicomTags", {}).get("SOPInstanceUID")
                            if not _p11_expected:
                                _p11_expected = _p11_entry.get("SOPInstanceUID")
                    elif isinstance(_p11_data, list) and _p11_data:
                        _p11_first = _p11_data[0]
                        if isinstance(_p11_first, dict):
                            _p11_expected = _p11_first.get("MainDicomTags", {}).get("SOPInstanceUID")
                            if not _p11_expected:
                                _p11_expected = _p11_first.get("SOPInstanceUID")
                        elif isinstance(_p11_first, str):
                            _p11_resp2 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/instances/{_p11_first}/simplified-tags", timeout=10)
                            _p11_tags = _p11_json.loads(_p11_resp2.read())
                            _p11_expected = _p11_tags.get("SOPInstanceUID")
                    if _p11_expected:
                        logger.info(f"Patch 11: Orthanc SOPInstanceUID: {_p11_expected}")
                        # Also sync PatientID from Orthanc to prevent "Multiple Patients"
                        _p11_pa = _p11_data
                        _p11_pid = None
                        if isinstance(_p11_pa, dict) and _p11_pa:
                            _p11_fk = next(iter(_p11_pa), None)
                            if _p11_fk is not None:
                                _p11_en = _p11_pa[_p11_fk]
                                if isinstance(_p11_en, dict):
                                    _p11_pid = _p11_en.get("MainDicomTags", {}).get("PatientID")
                        elif isinstance(_p11_pa, list) and _p11_pa:
                            _p11_fi = _p11_pa[0]
                            if isinstance(_p11_fi, dict):
                                _p11_pid = _p11_fi.get("MainDicomTags", {}).get("PatientID")
                            elif isinstance(_p11_fi, str):
                                try:
                                    _p11_r3 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/instances/{_p11_fi}/simplified-tags", timeout=10)
                                    _p11_pid = _p11_json.loads(_p11_r3.read()).get("PatientID")
                                except Exception:
                                    pass
                        if _p11_pid:
                            _p11_existing_pid = str(_p11_seg.PatientID) if hasattr(_p11_seg, 'PatientID') and _p11_seg.PatientID else None
                            if _p11_existing_pid and _p11_existing_pid != str(_p11_pid):
                                logger.warning(
                                    f"Patch 11: Orthanc PatientID {_p11_pid} differs from SEG's {_p11_existing_pid}, "
                                    f"keeping SEG's value (from source DICOM)"
                                )
                            elif not _p11_existing_pid:
                                _p11_seg.PatientID = str(_p11_pid)
                                _p11_mod = True
                                logger.info(f"Patch 11: Set SEG PatientID from Orthanc: {_p11_pid}")
            except Exception as _p11_oe:
                logger.warning(f"Patch 11: Orthanc query failed: {_p11_oe}")

            if _p11_expected is None:
                logger.warning("Patch 11: Orthanc query returned no result, falling back to file")
                _p11_expected = _p11_file_sop
                if _p11_expected:
                    logger.info(f"Patch 11: Fallback SOPInstanceUID from file: {_p11_expected}")

            if _p11_expected is None:
                logger.warning("Patch 11: Final fallback to series_dir name skipped (would be invalid SOP UID)")"""

if os.path.exists(PATCH11_CONVERT):
    with open(PATCH11_CONVERT) as f:
        _p11_content = f.read()

    # --- Upgrade path: replace old file-read+fallback with Orthanc-querying version ---
    if PATCH11_OLD_CODE_BLOCK in _p11_content and "Orthanc SOPInstanceUID" not in _p11_content:
        _p11_content = _p11_content.replace(PATCH11_OLD_CODE_BLOCK, PATCH11_NEW_ORTHANC)
        with open(PATCH11_CONVERT, "w") as f:
            f.write(_p11_content)
        print("convert.py Patch 11 UPGRADED: now queries Orthanc for correct SOPInstanceUID")
        patches_applied = True

    # --- Upgrade: add PatientID sync to existing Orthanc query (Patch 11D) ---
    # Detect convert.py that has Orthanc query but missing PatientID sync
    _p11d_old = '''                    if _p11_expected:
                        logger.info(f"Patch 11: Orthanc SOPInstanceUID: {_p11_expected}")
                except Exception as _p11_oe:
                    logger.warning(f"Patch 11: Orthanc query failed: {_p11_oe}")'''
    _p11d_new = '''                    if _p11_expected:
                        logger.info(f"Patch 11: Orthanc SOPInstanceUID: {_p11_expected}")
                        # Also sync PatientID from Orthanc to prevent "Multiple Patients"
                        _p11_pa = _p11_data
                        _p11_pid = None
                        if isinstance(_p11_pa, dict) and _p11_pa:
                            _p11_fk = next(iter(_p11_pa), None)
                            if _p11_fk is not None:
                                _p11_en = _p11_pa[_p11_fk]
                                if isinstance(_p11_en, dict):
                                    _p11_pid = _p11_en.get("MainDicomTags", {}).get("PatientID")
                        elif isinstance(_p11_pa, list) and _p11_pa:
                            _p11_fi = _p11_pa[0]
                            if isinstance(_p11_fi, dict):
                                _p11_pid = _p11_fi.get("MainDicomTags", {}).get("PatientID")
                            elif isinstance(_p11_fi, str):
                                try:
                                    _p11_r3 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/instances/{_p11_fi}/simplified-tags", timeout=10)
                                    _p11_pid = _p11_json.loads(_p11_r3.read()).get("PatientID")
                                except Exception:
                                    pass
                        if _p11_pid:
                            _p11_existing_pid = str(_p11_seg.PatientID) if hasattr(_p11_seg, 'PatientID') and _p11_seg.PatientID else None
                            if _p11_existing_pid and _p11_existing_pid != str(_p11_pid):
                                logger.warning(
                                    f"Patch 11: Orthanc PatientID {_p11_pid} differs from SEG's {_p11_existing_pid}, "
                                    f"keeping SEG's value (from source DICOM)"
                                )
                            elif not _p11_existing_pid:
                                _p11_seg.PatientID = str(_p11_pid)
                                _p11_mod = True
                                logger.info(f"Patch 11: Set SEG PatientID from Orthanc: {_p11_pid}")
                except Exception as _p11_oe:
                    logger.warning(f"Patch 11: Orthanc query failed: {_p11_oe}")'''
    if "Set SEG PatientID from Orthanc" not in _p11_content and _p11d_old in _p11_content:
        _p11_content = _p11_content.replace(_p11d_old, _p11d_new)
        with open(PATCH11_CONVERT, "w") as f:
            f.write(_p11_content)
        print("convert.py Patch 11D UPGRADED: added PatientID sync from Orthanc")
        patches_applied = True

    # --- Upgrade from old series-level query to instance-level with correct StudyUID ---
    _p11c_old = """            _p11_expected = None
            _p11_series_uid = _p11_pl.Path(series_dir).name
            try:
                _p11_q = _p11_json.dumps({"Level": "series", "Query": {"SeriesInstanceUID": _p11_series_uid}}).encode()
                _p11_req = _p11_urlreq.Request("http://orthanc-container:8042/tools/find", data=_p11_q, headers={"Content-Type": "application/json"})
                _p11_resp = _p11_urlreq.urlopen(_p11_req, timeout=10)
                _p11_sids = _p11_json.loads(_p11_resp.read())
                if _p11_sids:
                    _p11_resp2 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/series/{_p11_sids[0]}/instances", timeout=10)
                    _p11_insts = _p11_json.loads(_p11_resp2.read())
                    if _p11_insts:
                        _p11_first = _p11_insts[0]
                        if isinstance(_p11_first, dict):
                            _p11_expected = _p11_first.get("MainDicomTags", {}).get("SOPInstanceUID")
                        else:
                            _p11_resp3 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/instances/{_p11_first}/simplified-tags", timeout=10)
                            _p11_tags = _p11_json.loads(_p11_resp3.read())
                            _p11_expected = _p11_tags.get("SOPInstanceUID")
                        logger.info(f"Patch 11: Orthanc SOPInstanceUID: {_p11_expected}")
            except Exception as _p11_oe:
                logger.warning(f"Patch 11: Orthanc query failed: {_p11_oe}")"""
    _p11c_new = """            _p11_series_uid = _p11_pl.Path(series_dir).name
            # Read StudyInstanceUID from source DICOM for precise Orthanc query
            _p11_src_dir = _p11_pl.Path(series_dir)
            _p11_dcm_files = sorted(_p11_src_dir.glob("*.dcm"))
            _p11_study_uid = None
            if _p11_dcm_files:
                _p11_src = _p11_dr(str(_p11_dcm_files[0]), stop_before_pixels=True)
                if hasattr(_p11_src, "StudyInstanceUID"):
                    _p11_study_uid = str(_p11_src.StudyInstanceUID)
            # Only overwrite _p11_expected if Orthanc query succeeds (don't clear file-based value)
            if _p11_study_uid:
                try:
                    _p11_q = _p11_json.dumps({"Level": "instance", "Query": {"StudyInstanceUID": _p11_study_uid, "SeriesInstanceUID": _p11_series_uid}}).encode()
                    _p11_req = _p11_urlreq.Request("http://orthanc-container:8042/tools/find", data=_p11_q, headers={"Content-Type": "application/json"})
                    _p11_resp = _p11_urlreq.urlopen(_p11_req, timeout=10)
                    _p11_data = _p11_json.loads(_p11_resp.read())
                    if isinstance(_p11_data, dict):
                        _p11_first_key = next(iter(_p11_data), None)
                        if _p11_first_key is not None:
                            _p11_entry = _p11_data[_p11_first_key]
                            if isinstance(_p11_entry, dict):
                                _p11_expected = _p11_entry.get("MainDicomTags", {}).get("SOPInstanceUID")
                            if not _p11_expected:
                                _p11_expected = _p11_entry.get("SOPInstanceUID")
                    elif isinstance(_p11_data, list) and _p11_data:
                        _p11_first = _p11_data[0]
                        if isinstance(_p11_first, dict):
                            _p11_expected = _p11_first.get("MainDicomTags", {}).get("SOPInstanceUID")
                            if not _p11_expected:
                                _p11_expected = _p11_first.get("SOPInstanceUID")
                        elif isinstance(_p11_first, str):
                            _p11_resp2 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/instances/{_p11_first}/simplified-tags", timeout=10)
                            _p11_tags = _p11_json.loads(_p11_resp2.read())
                            _p11_expected = _p11_tags.get("SOPInstanceUID")
                    if _p11_expected:
                        logger.info(f"Patch 11: Orthanc SOPInstanceUID: {_p11_expected}")
                        # Also extract PatientID from Orthanc response to fix "Multiple Patients"
                        _p11_orthanc_patient_id = None
                        if isinstance(_p11_data, dict):
                            _p11_first_key = next(iter(_p11_data), None)
                            if _p11_first_key is not None:
                                _p11_entry = _p11_data[_p11_first_key]
                                if isinstance(_p11_entry, dict):
                                    _p11_orthanc_patient_id = _p11_entry.get("MainDicomTags", {}).get("PatientID")
                        elif isinstance(_p11_data, list) and _p11_data:
                            _p11_first = _p11_data[0]
                            if isinstance(_p11_first, dict):
                                _p11_orthanc_patient_id = _p11_first.get("MainDicomTags", {}).get("PatientID")
                            elif isinstance(_p11_first, str):
                                _p11_resp3 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/instances/{_p11_first}/simplified-tags", timeout=10)
                                _p11_tags2 = _p11_json.loads(_p11_resp3.read())
                                _p11_orthanc_patient_id = _p11_tags2.get("PatientID")
                        if _p11_orthanc_patient_id:
                            _p11_seg.PatientID = str(_p11_orthanc_patient_id)
                            _p11_mod = True
                            logger.info(f"Patch 11: Set SEG PatientID from Orthanc: {_p11_orthanc_patient_id}")
                except Exception as _p11_oe:
                    logger.warning(f"Patch 11: Orthanc query failed: {_p11_oe}")"""
    if _p11c_old in _p11_content:
        _p11_content = _p11_content.replace(_p11c_old, _p11c_new)
        with open(PATCH11_CONVERT, "w") as f:
            f.write(_p11_content)
        print("convert.py Patch 11C UPGRADED: fixed Orthanc query + PatientID sync")
        patches_applied = True

    elif PATCH11_MARKER not in _p11_content:
        # Find: the latency log line in nifti_to_dicom_seg wrapper function
        _p11_old = '''    logger.info(f"nifti_to_dicom_seg latency : {time.time() - start} (sec)")
    return output_file'''
        _p11_new = '''    # Patch 11: brute-force force ALL ReferencedSOPInstanceUID in SEG to use
    # the actual SOPInstanceUID from Orthanc (queried by series UID).  The
    # cache file's SOPInstanceUID may be stale, so we always ask Orthanc first.
    # This ensures the SEG references match what OHIF/Cornerstone loads via DICOMweb.
    if output_file and os.path.exists(output_file):
        try:
            import pathlib as _p11_pl
            from pydicom import dcmread as _p11_dr
            import urllib.request as _p11_urlreq
            import json as _p11_json
            _p11_seg = _p11_dr(output_file)
            _p11_mod = False
            _p11_total = 0
            _p11_all_sops = []

            # Query Orthanc for the actual SOPInstanceUID in this series
            _p11_expected = None
            _p11_series_uid = _p11_pl.Path(series_dir).name
            # Read both SOPInstanceUID and StudyInstanceUID from cached source DICOM
            _p11_src_dir = _p11_pl.Path(series_dir)
            _p11_dcm_files = sorted(_p11_src_dir.glob("*.dcm"))
            _p11_file_sop = None
            _p11_study_uid = None
            if _p11_dcm_files:
                _p11_src = _p11_dr(str(_p11_dcm_files[0]), stop_before_pixels=True)
                if hasattr(_p11_src, "SOPInstanceUID"):
                    _p11_file_sop = str(_p11_src.SOPInstanceUID)
                if hasattr(_p11_src, "StudyInstanceUID"):
                    _p11_study_uid = str(_p11_src.StudyInstanceUID)
                # Build per-frame SOP list from ALL cached DICOM files (not just first)
                for _p11_df in _p11_dcm_files:
                    _p11_tmp = _p11_dr(str(_p11_df), stop_before_pixels=True)
                    if hasattr(_p11_tmp, "SOPInstanceUID"):
                        _p11_all_sops.append(str(_p11_tmp.SOPInstanceUID))
            try:
                if _p11_study_uid:
                    # Query Orthanc at instance level with BOTH Study+Series UIDs for precise filtering
                    _p11_q = _p11_json.dumps({"Level": "instance", "Query": {"StudyInstanceUID": _p11_study_uid, "SeriesInstanceUID": _p11_series_uid}}).encode()
                    _p11_req = _p11_urlreq.Request("http://orthanc-container:8042/tools/find", data=_p11_q, headers={"Content-Type": "application/json"})
                    _p11_resp = _p11_urlreq.urlopen(_p11_req, timeout=10)
                    _p11_data = _p11_json.loads(_p11_resp.read())
                    if isinstance(_p11_data, dict):
                        _p11_first_key = next(iter(_p11_data), None)
                        if _p11_first_key is not None:
                            _p11_entry = _p11_data[_p11_first_key]
                            if isinstance(_p11_entry, dict):
                                _p11_expected = _p11_entry.get("MainDicomTags", {}).get("SOPInstanceUID")
                            if not _p11_expected:
                                _p11_expected = _p11_entry.get("SOPInstanceUID")
                    elif isinstance(_p11_data, list) and _p11_data:
                        _p11_first = _p11_data[0]
                        if isinstance(_p11_first, dict):
                            _p11_expected = _p11_first.get("MainDicomTags", {}).get("SOPInstanceUID")
                            if not _p11_expected:
                                _p11_expected = _p11_first.get("SOPInstanceUID")
                        elif isinstance(_p11_first, str):
                            _p11_resp2 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/instances/{_p11_first}/simplified-tags", timeout=10)
                            _p11_tags = _p11_json.loads(_p11_resp2.read())
                            _p11_expected = _p11_tags.get("SOPInstanceUID")
                    if _p11_expected:
                        logger.info(f"Patch 11: Orthanc SOPInstanceUID: {_p11_expected}")
                        # Also sync PatientID from Orthanc to prevent "Multiple Patients"
                        _p11_opa = None
                        if isinstance(_p11_data, dict):
                            _p11_fk = next(iter(_p11_data), None)
                            if _p11_fk is not None:
                                _p11_en = _p11_data[_p11_fk]
                                if isinstance(_p11_en, dict):
                                    _p11_opa = _p11_en.get("MainDicomTags", {}).get("PatientID")
                        elif isinstance(_p11_data, list) and _p11_data:
                            _p11_fi = _p11_data[0]
                            if isinstance(_p11_fi, dict):
                                _p11_opa = _p11_fi.get("MainDicomTags", {}).get("PatientID")
                            elif isinstance(_p11_fi, str):
                                try:
                                    _p11_r3 = _p11_urlreq.urlopen(f"http://orthanc-container:8042/instances/{_p11_fi}/simplified-tags", timeout=10)
                                    _p11_opa = _p11_json.loads(_p11_r3.read()).get("PatientID")
                                except Exception:
                                    pass
                        if _p11_opa:
                            _p11_existing_pid = str(_p11_seg.PatientID) if hasattr(_p11_seg, 'PatientID') and _p11_seg.PatientID else None
                            if _p11_existing_pid and _p11_existing_pid != str(_p11_opa):
                                logger.warning(
                                    f"Patch 11: Orthanc PatientID {_p11_opa} differs from SEG's {_p11_existing_pid}, "
                                    f"keeping SEG's value (from source DICOM)"
                                )
                            elif not _p11_existing_pid:
                                _p11_seg.PatientID = str(_p11_opa)
                                _p11_mod = True
                                logger.info(f"Patch 11: Set SEG PatientID from Orthanc: {_p11_opa}")
            except Exception as _p11_oe:
                logger.warning(f"Patch 11: Orthanc query failed: {_p11_oe}")

            if _p11_expected is None:
                logger.warning("Patch 11: Orthanc query returned no result, falling back to file")
                _p11_expected = _p11_file_sop
                if _p11_expected:
                    logger.info(f"Patch 11: Fallback SOPInstanceUID from file: {_p11_expected}")

            if _p11_expected is None:
                logger.warning(f"Patch 11: No SOP UID available from Orthanc or file, keeping original SEG refs")

            def _p11_force(item, uid):
                c = 0
                for e in item:
                    if e.keyword == "ReferencedSOPInstanceUID":
                        ov = str(e.value)
                        if ov != uid:
                            e.value = uid
                            c += 1
                    elif e.VR == "SQ" and e.value is not None:
                        for si in e.value:
                            c += _p11_force(si, uid)
                return c

            if hasattr(_p11_seg, "PerFrameFunctionalGroupsSequence"):
                for fi, fg in enumerate(_p11_seg.PerFrameFunctionalGroupsSequence):
                    _p11_uid = _p11_all_sops[fi] if fi < len(_p11_all_sops) else (_p11_expected or _p11_all_sops[0] if _p11_all_sops else None)
                    if _p11_uid:
                        _p11_total += _p11_force(fg, _p11_uid)
            if hasattr(_p11_seg, "SharedFunctionalGroupsSequence"):
                _p11_uid = _p11_all_sops[0] if _p11_all_sops else _p11_expected
                if _p11_uid:
                    for sfg in _p11_seg.SharedFunctionalGroupsSequence:
                        _p11_total += _p11_force(sfg, _p11_uid)
            if _p11_total > 0 or _p11_mod:
                _p11_seg.save_as(output_file)
                logger.info(f"Patch 11: Forced {_p11_total} ReferencedSOPInstanceUID -> {_p11_expected}")
        except Exception as _p11_e:
            logger.warning(f"Patch 11 SOP fix skipped: {_p11_e}")

    ### OHIF_PATCH_11_FORCE_SOP ###
    logger.info(f"nifti_to_dicom_seg latency : {time.time() - start} (sec)")
    return output_file'''
        if _p11_old in _p11_content:
            _p11_content = _p11_content.replace(_p11_old, _p11_new)
            with open(PATCH11_CONVERT, "w") as f:
                f.write(_p11_content)
            print("convert.py Patch 11: brute-force SOP fix applied to nifti_to_dicom_seg wrapper")
            patches_applied = True
        else:
            print("WARNING: Patch 11 — latency log pattern not found in convert.py")
    else:
        patches_applied = True
        print("convert.py: Patch 11 already applied")

# Patch 12: Inject model_name into label_info so SEG SeriesDescription reflects the model name
# This makes each SEG series distinguishable (instead of all showing "AIName")
if os.path.exists(INFER):
    with open(INFER) as f:
        _p12_content = f.read()
    _p12_marker = "### MONAI_P12_MODEL_NAME ###"
    if _p12_marker not in _p12_content:
        _p12_old = '''label_info = p.get("label_info") or result.get("params", {}).get("label_info")\n            if res_img and os.path.exists(res_img) and label_info:'''
        _p12_new = '''label_info = p.get("label_info") or result.get("params", {}).get("label_info")\n            if label_info and isinstance(label_info, list) and len(label_info) > 0 and isinstance(label_info[0], dict):\n                label_info[0]["model_name"] = model\n            ### MONAI_P12_MODEL_NAME ###\n            if res_img and os.path.exists(res_img) and label_info:'''
        if _p12_old in _p12_content:
            _p12_content = _p12_content.replace(_p12_old, _p12_new)
            # Also fix the second nifti_to_dicom_seg call in the dicom_seg output path
            _p12_old2 = '''dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, p.get("label_info") or result.get("params", {}).get("label_info") or result.get("params", {}).get("label_info"), use_itk=False)'''
            _p12_new2 = '''_li3 = p.get("label_info") or result.get("params", {}).get("label_info") or result.get("params", {}).get("label_info")\n        if _li3 and isinstance(_li3, list) and len(_li3) > 0 and isinstance(_li3[0], dict):\n            _li3[0]["model_name"] = model\n        dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, _li3, use_itk=False)'''
            if _p12_old2 in _p12_content:
                _p12_content = _p12_content.replace(_p12_old2, _p12_new2)
            with open(INFER, "w") as f:
                f.write(_p12_content)
            print("infer.py Patch 12: model_name injected into label_info for SEG SeriesDescription")
            patches_applied = True
        else:
            print("WARNING: Patch 12 — label_info pattern not found in infer.py")
    else:
        patches_applied = True
        print("infer.py: Patch 12 already applied")
else:
    patches_applied = True

# Patch 13: Remove all cache file modification from infer.py (prevents PatientID contamination)
# Earlier patches (3, 4, 7) may have injected code that modifies cached DICOM files
# on disk and re-uploads them to Orthanc with wrong PatientID/StudyInstanceUID.
# This cleanup ensures cached files are NEVER modified on disk.
PATCH13_MARKER = "### PATCH13_CACHE_CLEANUP ###"
if os.path.exists(INFER):
    with open(INFER) as f:
        _p13_content = f.read()

    if PATCH13_MARKER not in _p13_content:
        _p13_changed = False

        # Remove: pre-inject geometry + save_as(src_path) + re-upload to Orthanc
        # Pattern 1: Patch 3/4 style full pre-inject block
        _p13_old1 = '''                    # Pre-inject geometry into cached source BEFORE SEG generation
                    try:
                        dcm_files = list(pathlib.Path(image_path).glob("*"))
                        if dcm_files:
                            src_path = str(dcm_files[0])
                            src_ds = dcmread(src_path, stop_before_pixels=True)
                            needs_ipp = not hasattr(src_ds, 'ImagePositionPatient')
                            if not hasattr(src_ds, 'FrameOfReferenceUID') or needs_ipp:
                                src_full = dcmread(src_path)
                                if not hasattr(src_full, 'FrameOfReferenceUID'):
                                    src_full.FrameOfReferenceUID = "2.25." + str(int(hashlib.md5(str(src_full.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
                                if needs_ipp:
                                    src_full.ImagePositionPatient = [0, 0, 0]
                                    src_full.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                                    src_full.SliceThickness = 1.0
                                src_full.save_as(src_path)
                                with open(src_path, "rb") as f:
                                    resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                                logger.info(f"Pre-injected geometry into source (resp={resp.status_code})")
                    except Exception as e2:
                        logger.warning(f"Pre-inject geometry skipped: {e2}")'''
        _p13_new1 = '''                    # Geometry injection is handled in-memory by convert.py (Patch 8A/9A).
                    # Do NOT modify cached DICOM files on disk or re-upload to Orthanc.'''
        if _p13_old1 in _p13_content:
            _p13_content = _p13_content.replace(_p13_old1, _p13_new1)
            _p13_changed = True
            print("Patch 13: Removed pre-inject cache modification block")

        # Pattern 2: StudyInstanceUID injection + save_as(fpath) (20-space indent)
        _p13_old2 = '''                    # Inject study_uid into source DICOMs BEFORE SEG gen so highdicom inherits them
                    if source_study_uid:
                        try:
                            dcm_files = list(pathlib.Path(image_path).glob("*"))
                            for fpath in dcm_files:
                                ds = dcmread(str(fpath))
                                if str(ds.StudyInstanceUID) != source_study_uid:
                                    ds.StudyInstanceUID = source_study_uid
                                    ds.save_as(str(fpath))
                                    logger.info(f"Injected StudyInstanceUID into source: {fpath.name}")
                        except Exception as e:
                            logger.warning(f"Could not inject StudyInstanceUID into sources: {e}")
                        logger.info(f"Source StudyInstanceUID: {source_study_uid}")'''
        _p13_new2 = '''                    # StudyInstanceUID is inherited from source by convert.py (Patch 9B).
                    # Do NOT modify cached DICOM files on disk.
                    if source_study_uid:
                        logger.info(f"Source StudyInstanceUID: {source_study_uid}")'''
        if _p13_old2 in _p13_content:
            _p13_content = _p13_content.replace(_p13_old2, _p13_new2)
            _p13_changed = True
            print("Patch 13: Removed StudyInstanceUID injection + save_as(fpath)")

        if _p13_changed:
            # Add marker so this only runs once
            _p13_content += f"\n# {PATCH13_MARKER} - Cache modification removed\n"
            with open(INFER, "w") as f:
                f.write(_p13_content)
            print("Patch 13: Cache cleanup applied to infer.py")
            patches_applied = True
        else:
            print("Patch 13: No cache modification code found (already clean)")
    else:
        print("Patch 13: Already applied")

# Patch 14: Force explicit StudyInstanceUID on SEG from inference params
# The Django backend now passes the correct OP study_uid in inference params.
# This patch ensures the SEG always inherits that value, overriding any
# auto-generated or cache-contaminated StudyInstanceUID.
# This fixes SEGs appearing in separate studies instead of the OP's study.
PATCH14_MARKER = "### PATCH14_FORCE_STUDY_UID ###"
if os.path.exists(INFER):
    with open(INFER) as f:
        _p14_content = f.read()

    if PATCH14_MARKER not in _p14_content:
        # Find the push block: after dicom_seg_file is generated, before push to Orthanc
        _p14_old = '''                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, _li3, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:
                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")'''
        _p14_new = '''                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, _li3, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        # Patch 14: Force StudyInstanceUID from inference params (if provided)
                        # This ensures the SEG lands in the same study as the source OP.
                        _p14_study_uid = p.get("study_uid") or result.get("params", {}).get("study_uid")
                        if _p14_study_uid:
                            try:
                                _p14_seg = dcmread(dicom_seg_file)
                                if str(_p14_seg.StudyInstanceUID) != _p14_study_uid:
                                    _p14_seg.StudyInstanceUID = _p14_study_uid
                                    _p14_seg.save_as(dicom_seg_file)
                                    logger.info(f"Patch 14: Forced SEG StudyInstanceUID -> {_p14_study_uid}")
                            except Exception as _p14_e:
                                logger.warning(f"Patch 14: StudyUID fix skipped: {_p14_e}")
                        ### PATCH14_FORCE_STUDY_UID ###
                        with open(dicom_seg_file, "rb") as f:
                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")'''
        if _p14_old in _p14_content:
            _p14_content = _p14_content.replace(_p14_old, _p14_new)
            with open(INFER, "w") as f:
                f.write(_p14_content)
            print("Patch 14: Force StudyInstanceUID from inference params applied to infer.py")
            patches_applied = True
        else:
            # Try alternative pattern (from old-style AUTO_PUSH without _li3)
            _p14_old2 = '''                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        with open(dicom_seg_file, "rb") as f:
                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")'''
            _p14_new2 = '''                    dicom_seg_file = nifti_to_dicom_seg(image_path, res_img, label_info, use_itk=False)
                    if dicom_seg_file and os.path.exists(dicom_seg_file):
                        # Patch 14: Force StudyInstanceUID from inference params (if provided)
                        _p14_study_uid = p.get("study_uid") or result.get("params", {}).get("study_uid")
                        if _p14_study_uid:
                            try:
                                _p14_seg = dcmread(dicom_seg_file)
                                if str(_p14_seg.StudyInstanceUID) != _p14_study_uid:
                                    _p14_seg.StudyInstanceUID = _p14_study_uid
                                    _p14_seg.save_as(dicom_seg_file)
                                    logger.info(f"Patch 14: Forced SEG StudyInstanceUID -> {_p14_study_uid}")
                            except Exception as _p14_e:
                                logger.warning(f"Patch 14: StudyUID fix skipped: {_p14_e}")
                        ### PATCH14_FORCE_STUDY_UID ###
                        with open(dicom_seg_file, "rb") as f:
                            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
                            logger.info(f"Pushed DICOM-SEG to Orthanc: {resp.status_code}")'''
            if _p14_old2 in _p14_content:
                _p14_content = _p14_content.replace(_p14_old2, _p14_new2)
                with open(INFER, "w") as f:
                    f.write(_p14_content)
                print("Patch 14: Force StudyInstanceUID from inference params applied to infer.py")
                patches_applied = True
            else:
                print("WARNING: Patch 14 — DICOM-SEG push pattern not found in infer.py")
    else:
        print("Patch 14: Already applied")


# Patch 15: Fix dicom_web_download_series crash when SeriesInstanceUID has hash suffix
# and when DICOMWeb search returns empty results
DICOM_PY = "/usr/local/lib/python3.10/dist-packages/monailabel/datastore/utils/dicom.py"
if os.path.exists(DICOM_PY):
    with open(DICOM_PY) as f:
        content = f.read()

    marker = "### PATCH_HASH_SUFFIX ###"
    if marker not in content:
        old_dws_code = '''    # Limitation for DICOMWeb Client as it needs StudyInstanceUID to fetch series
    if not study_id:
        meta = Dataset.from_json(
            [
                series
                for series in client.search_for_series(search_filters={"SeriesInstanceUID": series_id})
                if series["0020000E"]["Value"] == [series_id]
            ][0]
        )
        study_id = str(meta["StudyInstanceUID"].value)'''

        new_dws_code = '''    # Limitation for DICOMWeb Client as it needs StudyInstanceUID to fetch series
    if not study_id:
        ### PATCH_HASH_SUFFIX ###
        # Fix: handle hash-suffixed SeriesInstanceUID (e.g. ...UID.XYZ12345),
        # empty DICOMWeb search results, and cross-patient collisions gracefully
        import re as _re
        search_results = client.search_for_series(search_filters={"SeriesInstanceUID": series_id})
        filtered = [
            series for series in search_results
            if series.get("0020000E", {}).get("Value") == [series_id]
        ]

        # If no results and series_id ends with .XXXXXXXX (hash suffix), retry with base UID
        if not filtered:
            base_match = _re.match(r'^(.+?)\.[0-9a-fA-F]{8}$', series_id)
            if base_match:
                base_uid = base_match.group(1)
                logger.info(f"DICOMWeb: no results for {series_id[:60]}..., retrying with base UID {base_uid[:60]}...")
                search_results = client.search_for_series(search_filters={"SeriesInstanceUID": base_uid})
                filtered = [
                    series for series in search_results
                    if series.get("0020000E", {}).get("Value") == [base_uid]
                ]
                if filtered:
                    series_id = base_uid

        if not filtered:
            raise Exception(f"Series not found via DICOMWeb: {series_id[:60]}...")

        # Handle cross-patient collisions: same SeriesInstanceUID across multiple studies
        if len(filtered) > 1:
            suids = [str(s.get('0020000D',{}).get('Value',['?'])[0])[:30] for s in filtered]
            logger.warning(
                f"DICOMWeb: {len(filtered)} studies share Series {series_id[:40]}... "
                f"StudyInstanceUIDs: {suids[:5]}"
            )
            # Use the LAST result (most recently added in Orthanc ordering)
            filtered = [filtered[-1]]
            logger.info(f"DICOMWeb: using last StudyInstanceUID for {series_id[:40]}...")

        meta = Dataset.from_json(filtered[0])
        study_id = str(meta["StudyInstanceUID"].value)'''

        if old_dws_code in content:
            content = content.replace(old_dws_code, new_dws_code)
            with open(DICOM_PY, "w") as f:
                f.write(content)
            print("dicom.py: fixed dicom_web_download_series for hash-suffixed UIDs + empty results")
            patches_applied = True
        else:
            print("WARNING: Patch 15 — dicom_web_download_series pattern not found in dicom.py")
    else:
        patches_applied = True
        print("dicom.py: Patch 15 already applied")


# Patch 16: Thread study_uid from infer request into DICOMWebDatastore
# so dicom_web_download_series can filter by correct study when
# multiple studies share the same SeriesInstanceUID.
# Also adds cross-patient collision logging.
if os.path.exists(DICOM_PY):
    with open(DICOM_PY) as f:
        content = f.read()

    marker16 = "### PATCH_STUDY_HINT ###"
    if marker16 not in content:
        # --- DICOM_PY: Add _study_id_hint to DICOMWebDatastore ---
        old_init = '''    def __init__(self, studies, cache_dir, client, fetch_by_frame=False, convert_to_nifti=True, search_filter=None):
        super().__init__(studies, cache_dir, auto_reload=False)
        self._client: DICOMwebClient = client
        self._fetch_by_frame = fetch_by_frame
        self._convert_to_nifti = convert_to_nifti
        self._search_filter = search_filter or json.loads(os.environ.get("MONAI_LABEL_DICOMWEB_SEARCH_FILTER", "{}"))'''

        new_init = '''    def __init__(self, studies, cache_dir, client, fetch_by_frame=False, convert_to_nifti=True, search_filter=None):
        super().__init__(studies, cache_dir, auto_reload=False)
        self._client: DICOMwebClient = client
        self._fetch_by_frame = fetch_by_frame
        self._convert_to_nifti = convert_to_nifti
        self._search_filter = search_filter or json.loads(os.environ.get("MONAI_LABEL_DICOMWEB_SEARCH_FILTER", "{}"))
        ### PATCH_STUDY_HINT ###
        self._study_id_hint = None  # set by infer endpoint to disambiguate cross-patient collisions'''

        if old_init in content:
            content = content.replace(old_init, new_init)
            with open(DICOM_PY, "w") as f:
                f.write(content)
            print("dicom.py: added _study_id_hint to DICOMWebDatastore")
            patches_applied = True
        else:
            print("WARNING: Patch 16A — DICOMWebDatastore __init__ pattern not found")

        # --- DICOM_PY: Pass study_id_hint to dicom_web_download_series ---
        old_get_uri = '''    def get_image_uri(self, image_id: str) -> str:
        logger.info(f"Image ID: {image_id}")
        image_dir = os.path.realpath(os.path.join(self._datastore.image_path(), image_id))
        logger.info(f"Image Dir (cache): {image_dir}")

        if not os.path.exists(image_dir) or not os.listdir(image_dir):
            dicom_web_download_series(None, image_id, image_dir, self._client, self._fetch_by_frame)'''

        new_get_uri = '''    def get_image_uri(self, image_id: str) -> str:
        ### PATCH_STUDY_HINT ###
        logger.info(f"Image ID: {image_id}")
        image_dir = os.path.realpath(os.path.join(self._datastore.image_path(), image_id))
        logger.info(f"Image Dir (cache): {image_dir}")

        if not os.path.exists(image_dir) or not os.listdir(image_dir):
            study_hint = getattr(self, '_study_id_hint', None)
            if study_hint:
                logger.info(f"Using study_id hint: {str(study_hint)[:40]}...")
            dicom_web_download_series(study_hint, image_id, image_dir, self._client, self._fetch_by_frame)
            # Clear hint after use
            self._study_id_hint = None'''

        if old_get_uri in content:
            content = content.replace(old_get_uri, new_get_uri)
            with open(DICOM_PY, "w") as f:
                f.write(content)
            print("dicom.py: get_image_uri uses study_id hint")
            patches_applied = True
        else:
            print("WARNING: Patch 16B — get_image_uri pattern not found in dicom.py")
    else:
        patches_applied = True
        print("dicom.py: Patch 16 already applied")


# Patch 17: Set study_id hint on datastore in infer.py before calling instance.infer()
# The study_uid comes from the request params (p.get("study_uid") or request.get("study_uid"))
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    marker17 = "### PATCH_STUDY_HINT_INFER ###"
    if marker17 not in content:
        old_infer_call = '''    logger.info(f"Infer Request: {request}")
    result = instance.infer(request)'''

        new_infer_call = '''    ### PATCH_STUDY_HINT_INFER ###
    logger.info(f"Infer Request: {request}")
    # Pass study_uid as hint to DICOMWebDatastore to disambiguate
    # cross-patient collisions when multiple studies share the same SeriesInstanceUID
    study_uid_hint = p.get("study_uid") or request.get("study_uid")
    ds = instance.datastore()
    if hasattr(ds, '_study_id_hint') and study_uid_hint:
        ds._study_id_hint = study_uid_hint
    result = instance.infer(request)'''

        if old_infer_call in content:
            content = content.replace(old_infer_call, new_infer_call)
            with open(INFER, "w") as f:
                f.write(content)
            print("infer.py: study_uid hint passed to DICOMWebDatastore before infer")
            patches_applied = True
        else:
            print("WARNING: Patch 17 — infer call pattern not found in infer.py")
    else:
        patches_applied = True
        print("infer.py: Patch 17 already applied")


# Patch 18: A study hint must invalidate the series-only cache before inference.
# Legacy OP data can reuse one SeriesInstanceUID in many studies, so retaining
# that cache silently serves the previously segmented patient's DICOM.
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    marker18 = "### PATCH_STUDY_CACHE_ISOLATION ###"
    if marker18 not in content:
        old_hint = '''    if hasattr(ds, '_study_id_hint') and study_uid_hint:
        ds._study_id_hint = study_uid_hint
    result = instance.infer(request)'''

        new_hint = '''    if hasattr(ds, '_study_id_hint') and study_uid_hint:
        ### PATCH_STUDY_CACHE_ISOLATION ###
        ds._study_id_hint = study_uid_hint
        # The default cache key is only SeriesInstanceUID. Purge it so
        # get_image_uri() must download from the explicitly requested study.
        try:
            _study_cache_image = request.get("image") or image
            _study_cache_dir = os.path.realpath(
                os.path.join(ds._datastore.image_path(), _study_cache_image)
            )
            _study_cache_nifti = os.path.realpath(
                os.path.join(ds._datastore.image_path(), f"{_study_cache_image}.nii.gz")
            )
            if os.path.isdir(_study_cache_dir):
                shutil.rmtree(_study_cache_dir, ignore_errors=True)
            if os.path.isfile(_study_cache_nifti):
                os.unlink(_study_cache_nifti)
            logger.info(
                f"Cleared series-only cache for study-specific inference: "
                f"{str(study_uid_hint)[:40]}..."
            )
        except Exception as cache_error:
            logger.warning(f"Could not clear study-specific DICOM cache: {cache_error}")
    result = instance.infer(request)'''

        if old_hint in content:
            content = content.replace(old_hint, new_hint)
            with open(INFER, "w") as f:
                f.write(content)
            print("infer.py: study-specific requests now invalidate series-only cache")
            patches_applied = True
        else:
            print("WARNING: Patch 18 — study hint block not found in infer.py")
    else:
        patches_applied = True
        print("infer.py: Patch 18 already applied")


# Patch 19: Patch 16 used the constructor signature from an older MONAI Label.
# Current images accept (client, search_filter, cache_path, ...).
DATASTORE_DICOM_PY = (
    "/usr/local/lib/python3.10/dist-packages/monailabel/datastore/dicom.py"
)
if os.path.exists(DATASTORE_DICOM_PY):
    with open(DATASTORE_DICOM_PY) as f:
        content = f.read()

    marker19 = "### PATCH_CURRENT_STUDY_HINT ###"
    if marker19 not in content:
        current_init = '''        self._convert_to_nifti = convert_to_nifti

        uri_hash = md5_digest(self._client.base_url)'''
        current_init_patched = '''        self._convert_to_nifti = convert_to_nifti
        ### PATCH_CURRENT_STUDY_HINT ###
        self._study_id_hint = None

        uri_hash = md5_digest(self._client.base_url)'''

        current_download = (
            "            dicom_web_download_series(None, image_id, image_dir, "
            "self._client, self._fetch_by_frame)"
        )
        current_download_patched = '''            study_hint = getattr(self, "_study_id_hint", None)
            if study_hint:
                logger.info(f"Using explicit StudyInstanceUID: {study_hint}")
            dicom_web_download_series(
                study_hint, image_id, image_dir, self._client, self._fetch_by_frame
            )
            self._study_id_hint = None'''

        changed19 = False
        if current_init in content:
            content = content.replace(current_init, current_init_patched, 1)
            changed19 = True
        if current_download in content:
            content = content.replace(current_download, current_download_patched, 1)
            changed19 = True

        if changed19:
            with open(DATASTORE_DICOM_PY, "w") as f:
                f.write(content)
            print("dicom.py: current datastore now consumes explicit study hint")
            patches_applied = True
        else:
            print("WARNING: Patch 19 — current DICOM datastore patterns not found")
    else:
        patches_applied = True
        print("dicom.py: Patch 19 already applied")


# Patch 20: OP/fundus DICOM-SEG geometry for OHIF.
# Retinal models operate on one selected 2D slice even when the source OP
# series contains multiple captures. Normalize the NIfTI mask to exactly one
# SEG frame and reference only one source DICOM so OHIF sees matching
# Rows/Columns for every SEG frame.
PATCH20_MARKER = "OHIF OP SEG: retinal models output one 2D mask"
if os.path.exists(CONVERT):
    with open(CONVERT) as f:
        content = f.read()

    if PATCH20_MARKER not in content:
        old_mask20 = '''        # Fix dimension mismatch: mask z may not match source instance count
        if image_datasets:
            ref = image_datasets[0]
            expected = (len(image_datasets), int(ref.Rows), int(ref.Columns))
            mask_arr = SimpleITK.GetArrayFromImage(mask)
            if mask_arr.shape != expected and mask_arr.size == np.prod(expected):
                import itertools
                for perm in itertools.permutations(range(mask_arr.ndim)):
                    t = np.transpose(mask_arr, perm)
                    if t.shape == expected:
                        mask = SimpleITK.GetImageFromArray(t.astype(np.uint16))
                        logger.info(f"Reshaped mask {mask_arr.shape} -> {expected} via perm {perm}")
                        break

        output_file = tempfile.NamedTemporaryFile(suffix=".dcm").name'''
        new_mask20 = '''        # OHIF OP SEG: retinal models output one 2D mask
        # OHIF/OP fix: retinal models output one 2D mask.  The source OP
        # series can contain several capture instances, and NIfTI axes may be
        # HxWx1 or WxHx1.  Normalize to exactly one SEG frame with Rows/Columns
        # matching the single referenced OP image.
        if image_datasets:
            ref = image_datasets[0]
            ref_rows = int(ref.Rows)
            ref_cols = int(ref.Columns)
            mask_arr = SimpleITK.GetArrayFromImage(mask)
            original_shape = mask_arr.shape

            def _as_single_frame(arr, rows, cols):
                arr = np.asarray(arr)
                if arr.ndim == 2:
                    if arr.shape == (rows, cols):
                        return arr[None, :, :]
                    if arr.shape == (cols, rows):
                        return arr.T[None, :, :]
                if arr.ndim == 3:
                    import itertools
                    for perm in itertools.permutations(range(3)):
                        t = np.transpose(arr, perm)
                        if t.shape == (1, rows, cols):
                            return t
                        if t.shape == (1, cols, rows):
                            return np.transpose(t, (0, 2, 1))
                    for axis in range(3):
                        moved = np.moveaxis(arr, axis, 0)
                        if moved.shape[1:] == (rows, cols):
                            return moved[:1]
                        if moved.shape[1:] == (cols, rows):
                            return np.transpose(moved[:1], (0, 2, 1))
                return None

            single_frame = _as_single_frame(mask_arr, ref_rows, ref_cols)
            if single_frame is not None:
                if single_frame.shape != mask_arr.shape:
                    logger.info(
                        f"OHIF OP SEG: normalized mask {original_shape} -> {single_frame.shape} "
                        f"for source Rows/Columns=({ref_rows}, {ref_cols})"
                    )
                mask = SimpleITK.GetImageFromArray(single_frame.astype(np.uint16))
                if len(image_datasets) != 1:
                    logger.info(
                        f"OHIF OP SEG: using single source DICOM for SEG reference "
                        f"instead of {len(image_datasets)} instances"
                    )
                    image_datasets = [ref]
            else:
                logger.warning(
                    f"OHIF OP SEG: could not normalize mask shape {original_shape} "
                    f"to source Rows/Columns=({ref_rows}, {ref_cols})"
                )

        output_file = tempfile.NamedTemporaryFile(suffix=".dcm").name'''
        if old_mask20 in content:
            content = content.replace(old_mask20, new_mask20, 1)
            with open(CONVERT, "w") as f:
                f.write(content)
            print("convert.py Patch 20: OP SEG single-frame OHIF geometry applied")
            patches_applied = True
        else:
            print("WARNING: Patch 20 — mask dimension block not found in convert.py")
    else:
        patches_applied = True
        print("convert.py: Patch 20 already applied")


# Patch 21: Keep OP/fundus SEG per-frame references on the selected source.
# Patch 20 makes OP SEG output single-source, but older Patch 11 can later
# rewrite multi-frame SEG references across every cached OP instance.  For
# fundus SEG this makes OHIF compare SEG frames against different source image
# geometry.  OP models are 2D, so all frames must reference the same selected
# source SOPInstanceUID.
PATCH21_MARKER = "OHIF OP SEG: force all SEG frame refs to selected source"
if os.path.exists(CONVERT):
    with open(CONVERT) as f:
        content = f.read()

    if PATCH21_MARKER not in content:
        old_refs21 = '''            if hasattr(_p11_seg, "PerFrameFunctionalGroupsSequence"):
                for fi, fg in enumerate(_p11_seg.PerFrameFunctionalGroupsSequence):
                    _p11_uid = _p11_all_sops[fi] if fi < len(_p11_all_sops) else (_p11_expected or _p11_all_sops[0] if _p11_all_sops else None)
                    if _p11_uid:
                        _p11_total += _p11_force(fg, _p11_uid)'''
        new_refs21 = '''            # OHIF OP SEG: force all SEG frame refs to selected source.
            # Retinal OP models emit 2D segment frames for one selected source
            # image.  Do not spread multi-segment frames across the cached OP
            # capture series.
            if _p11_all_sops:
                try:
                    _p11_src_mod = str(getattr(_p11_src, "Modality", "")) if "_p11_src" in locals() else ""
                    if _p11_src_mod == "OP":
                        _p11_all_sops = [_p11_all_sops[0]]
                        _p11_expected = _p11_all_sops[0]
                        logger.info(f"OHIF OP SEG: forcing all SEG frame references to selected source SOP {_p11_all_sops[0]}")
                except Exception as _p11_op_ref_e:
                    logger.warning(f"OHIF OP SEG: could not force single-source references: {_p11_op_ref_e}")

            if hasattr(_p11_seg, "PerFrameFunctionalGroupsSequence"):
                for fi, fg in enumerate(_p11_seg.PerFrameFunctionalGroupsSequence):
                    _p11_uid = _p11_all_sops[fi] if fi < len(_p11_all_sops) else (_p11_expected or _p11_all_sops[0] if _p11_all_sops else None)
                    if _p11_uid:
                        _p11_total += _p11_force(fg, _p11_uid)'''
        if old_refs21 in content:
            content = content.replace(old_refs21, new_refs21, 1)
            content = content.replace(
                "### OHIF_PATCH_11_FORCE_SOP ###",
                f"### {PATCH21_MARKER} ###\n    ### OHIF_PATCH_11_FORCE_SOP ###",
                1,
            )
            with open(CONVERT, "w") as f:
                f.write(content)
            print("convert.py Patch 21: OP SEG single-source frame references applied")
            patches_applied = True
        else:
            print("WARNING: Patch 21 — Patch 11 per-frame reference block not found in convert.py")
    else:
        patches_applied = True
        print("convert.py: Patch 21 already applied")
else:
    print(f"WARNING: convert.py not found for Patch 21: {CONVERT}")


# Patch 22: Let backend drive per-source-instance OP segmentation.
# The backend prepares MONAI's DICOM cache with exactly one source DICOM and
# passes source_sop_instance_uid.  Keep that DICOM directory intact, but clear
# stale derived NIfTI/local-index state so MONAI converts the current single
# cached instance instead of re-downloading the whole OP series.
PATCH22_MARKER = "OHIF OP SEG: preserve single-instance cache"
if os.path.exists(INFER):
    with open(INFER) as f:
        content = f.read()

    if PATCH22_MARKER not in content:
        old_cache22 = '''            if os.path.isdir(_study_cache_dir):
                shutil.rmtree(_study_cache_dir, ignore_errors=True)
            if os.path.isfile(_study_cache_nifti):
                os.unlink(_study_cache_nifti)
            logger.info(
                f"Cleared series-only cache for study-specific inference: "
                f"{str(study_uid_hint)[:40]}..."
            )'''
        new_cache22 = '''            _source_sop_uid = p.get("source_sop_instance_uid") or request.get("source_sop_instance_uid")
            if _source_sop_uid:
                # OHIF OP SEG: preserve single-instance cache
                # Backend already populated _study_cache_dir with one DICOM.
                # Remove stale derived files/index entries only.
                if os.path.isfile(_study_cache_nifti):
                    os.unlink(_study_cache_nifti)
                try:
                    if hasattr(ds._datastore, "_images"):
                        ds._datastore._images.pop(_study_cache_image, None)
                except Exception:
                    pass
                logger.info(
                    f"Preserved single-instance cache for SOP {_source_sop_uid}; "
                    f"cleared derived NIfTI for {str(study_uid_hint)[:40]}..."
                )
            else:
                if os.path.isdir(_study_cache_dir):
                    shutil.rmtree(_study_cache_dir, ignore_errors=True)
                if os.path.isfile(_study_cache_nifti):
                    os.unlink(_study_cache_nifti)
                logger.info(
                    f"Cleared series-only cache for study-specific inference: "
                    f"{str(study_uid_hint)[:40]}..."
                )'''
        if old_cache22 in content:
            content = content.replace(old_cache22, new_cache22, 1)
            with open(INFER, "w") as f:
                f.write(content)
            print("infer.py Patch 22: preserve single-instance cache for OP SEG")
            patches_applied = True
        else:
            print("WARNING: Patch 22 — study cache clear block not found in infer.py")
    else:
        patches_applied = True
        print("infer.py: Patch 22 already applied")
else:
    print(f"WARNING: infer.py not found for Patch 22: {INFER}")

# Patch 23: Match DICOM segment metadata by the actual numeric label value.
# MONAI's upstream converter uses the position in unique_labels, which shifts
# names/colors whenever a lower-numbered lesion class is absent.
PATCH23_MARKER = "OHIF SEG: map metadata by numeric label"
if os.path.exists(CONVERT):
    with open(CONVERT) as f:
        content = f.read()

    if PATCH23_MARKER not in content:
        old_label_info23 = '''        info = label_info[i] if label_info and i < len(label_info) else {}
        name = info.get("name", "unknown")'''
        new_label_info23 = '''        # OHIF SEG: map metadata by numeric label
        info_index = int(idx) - 1
        info = label_info[info_index] if label_info and 0 <= info_index < len(label_info) else {}
        name = info.get("name", "unknown")'''
        if old_label_info23 in content:
            content = content.replace(old_label_info23, new_label_info23, 1)
            with open(CONVERT, "w") as f:
                f.write(content)
            print("convert.py Patch 23: numeric label metadata mapping applied")
            patches_applied = True
        else:
            print("WARNING: Patch 23 — label metadata loop not found in convert.py")
    else:
        patches_applied = True
        print("convert.py: Patch 23 already applied")
else:
    print(f"WARNING: convert.py not found for Patch 23: {CONVERT}")


if not patches_applied:
    print("No patches needed (already applied or versions mismatch)")
else:
    print("Patches applied successfully")
