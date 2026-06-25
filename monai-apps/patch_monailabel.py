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
        logger.info

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
        for _gi, _gds in enumerate(image_datasets):
            # Capture StudyInstanceUID from first source for post-processing
            if _src_study_uid_geom is None and hasattr(_gds, "StudyInstanceUID"):
                _src_study_uid_geom = str(_gds.StudyInstanceUID)
            # Assign a unique per-slice FrameOfReferenceUID derived from SOPInstanceUID
            if not hasattr(_gds, "FrameOfReferenceUID"):
                _gds.FrameOfReferenceUID = (
                    "2.25." + str(int(_ohif_hl.md5(str(_gds.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
                )
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
        # OHIF fix: enforce ReferencedSOPInstanceUID in ALL functional groups sequences.
        # Cornerstone3D reads both PerFrameFunctionalGroupsSequence AND
        # SharedFunctionalGroupsSequence.  Also handles ReferencedImageSequence
        # as a fallback path.
        if image_datasets:
            _p10_valid_sops = {str(ds.SOPInstanceUID) for ds in image_datasets if hasattr(ds, "SOPInstanceUID")}
            _p10_sop_list = [str(ds.SOPInstanceUID) for ds in image_datasets if hasattr(ds, "SOPInstanceUID")]
            if _p10_valid_sops:
                # Validate frame count
                if hasattr(dcm, "PerFrameFunctionalGroupsSequence"):
                    _nf = len(dcm.PerFrameFunctionalGroupsSequence)
                    _ns = len(_p10_sop_list)
                    if _nf != _ns:
                        logger.warning(
                            f"Frame count mismatch: SEG has {_nf} frames "
                            f"but source has {_ns} images"
                        )

                def _fix_sop_ref_p9(_fg_item, _frame_idx, _sop_list, _uid_set):
                    _lm = False
                    # Path 1: DerivationImageSequence > SourceImageSequence
                    if hasattr(_fg_item, "DerivationImageSequence"):
                        for _d in _fg_item.DerivationImageSequence:
                            if hasattr(_d, "SourceImageSequence"):
                                for _sr in _d.SourceImageSequence:
                                    if not hasattr(_sr, "ReferencedSOPInstanceUID"):
                                        continue
                                    _cu = str(_sr.ReferencedSOPInstanceUID)
                                    if _cu not in _uid_set:
                                        _rn = _sop_list[_frame_idx] if _frame_idx < len(_sop_list) else _sop_list[0]
                                        logger.warning(
                                            f"Frame {_frame_idx}: ReferencedSOPInstanceUID "
                                            f"{_cu[:60]}... not in source set -> patching to {_rn[:60]}..."
                                        )
                                        _sr.ReferencedSOPInstanceUID = _rn
                                        _lm = True
                    # Path 2: ReferencedImageSequence (direct)
                    if hasattr(_fg_item, "ReferencedImageSequence"):
                        for _sr in _fg_item.ReferencedImageSequence:
                            if not hasattr(_sr, "ReferencedSOPInstanceUID"):
                                continue
                            _cu = str(_sr.ReferencedSOPInstanceUID)
                            if _cu not in _uid_set:
                                _rn = _sop_list[_frame_idx] if _frame_idx < len(_sop_list) else _sop_list[0]
                                logger.warning(
                                    f"Frame {_frame_idx} (ReferencedImageSequence): "
                                    f"ReferencedSOPInstanceUID {_cu[:60]}... -> patching to {_rn[:60]}..."
                                )
                                _sr.ReferencedSOPInstanceUID = _rn
                                _lm = True
                    return _lm

                # Fix PerFrameFunctionalGroupsSequence
                if hasattr(dcm, "PerFrameFunctionalGroupsSequence"):
                    for _p10_fi, _p10_fg in enumerate(dcm.PerFrameFunctionalGroupsSequence):
                        if _fix_sop_ref_p9(_p10_fg, _p10_fi, _p10_sop_list, _p10_valid_sops):
                            pass  # modifications tracked inside helper

                # Fix SharedFunctionalGroupsSequence
                if hasattr(dcm, "SharedFunctionalGroupsSequence"):
                    for _sfg in dcm.SharedFunctionalGroupsSequence:
                        for _sfi in range(len(_p10_sop_list)):
                            _fix_sop_ref_p9(_sfg, _sfi, _p10_sop_list, _p10_valid_sops)
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

    run_seg = request.get("run_segmentation", True)
    instance = app_instance()
    SEG_MODELS = ["optic_disc_cup", "vessel_seg", "lesion_seg"]

    labels = {}
    if run_seg:
        for m in SEG_MODELS:
            try:
                r = instance.infer({"model": m, "image": image, "result_extension": ".nrrd", "result_dtype": "uint8", "result_compress": False})
                f = r.get("file") or r.get("label")
                if f and os.path.exists(f):
                    labels[m] = f
                    logger.info("Segmentation %s -> %s", m, f)
            except Exception as e:
                logger.error("Segmentation %s failed: %s", m, e)

    optic = {"disc_area_px": 0, "cup_area_px": 0, "cup_disc_ratio": 0.0}
    if "optic_disc_cup" in labels:
        try:
            import nrrd
            data, _ = nrrd.read(labels["optic_disc_cup"])
            if data.ndim == 3:
                data = data[0] if data.shape[0] == 1 else data.squeeze()
            disc = int(np.sum(data == 1))
            cup = int(np.sum(data == 2))
            ratio = cup / disc if disc > 0 else 0.0
            optic = {"disc_area_px": disc, "cup_area_px": cup, "cup_disc_ratio": round(ratio, 4)}
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
        try:
            import nrrd
            data, _ = nrrd.read(labels["vessel_seg"])
            if data.ndim == 3:
                data = data[0] if data.shape[0] == 1 else data.squeeze()
            total = int(data.size)
            v = int(np.sum(data > 0))
            vessel = {"coverage_pct": round(v / total * 100, 2) if total > 0 else 0.0, "pixel_count": v}
        except Exception as e:
            logger.error("Vessel quantification failed: %s", e)

    lesion = {"microaneurysms": 0, "hemorrhages": 0, "exudates": 0, "coverage_pct": 0.0}
    if "lesion_seg" in labels:
        try:
            import nrrd
            data, _ = nrrd.read(labels["lesion_seg"])
            if data.ndim == 3:
                data = data[0] if data.shape[0] == 1 else data.squeeze()
            total = int(data.size)
            ma = int(np.sum(data == 1))
            he = int(np.sum(data == 2))
            ex = int(np.sum(data == 3))
            any_lesion = int(np.sum(data > 0))
            lesion = {
                "microaneurysms": ma, "hemorrhages": he, "exudates": ex,
                "coverage_pct": round(any_lesion / total * 100, 2) if total > 0 else 0.0,
            }
        except Exception as e:
            logger.error("Lesion quantification failed: %s", e)

    dr = {"grade": "Unknown", "confidence": 0.0, "probabilities": []}
    try:
        r = instance.infer({"model": "dr_classification", "image": image})
        if r:
            p = r.get("params", {})
            predictions = p.get("prediction", [])
            dr["probabilities"] = [{"label": pred["label"], "score": pred["score"]} for pred in predictions]
            if predictions:
                top = max(predictions, key=lambda x: x["score"])
                dr["grade"] = top["label"]
                dr["confidence"] = top["score"]
    except Exception as e:
        logger.error("DR classification failed: %s", e)

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

    report = {
        "dr_classification": dr,
        "lesions": lesion,
        "optic_disc_cup": optic,
        "glaucoma": glaucoma,
        "vessels": vessel,
        "gradcam_image": gradcam_b64,
        "clahe_image": clahe_b64,
    }

    try:
        study_uid = request.get("study_uid", "1.2.3.4.5.6.7.8.9")
        series_uid = request.get("series_uid", None)

        ds = Dataset()
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.88.22"
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.10.1234"
        ds.file_meta = file_meta
        ds.PatientName = ""
        ds.PatientID = ""
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid or generate_uid()
        ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.Modality = "SR"
        ds.SeriesDescription = "AI Ophthalmology Report"

        lines = [
            "AI Ophthalmology Report",
            "",
            "DR Classification:",
            "  Grade: " + dr.get("grade", "N/A"),
            "  Confidence: " + ("{:.0%}".format(dr.get("confidence", 0))),
            "",
            "Lesion Analysis:",
            "  Microaneurysms: " + str(lesion.get("microaneurysms", 0)),
            "  Hemorrhages: " + str(lesion.get("hemorrhages", 0)),
            "  Exudates: " + str(lesion.get("exudates", 0)),
            "  Coverage: " + "{:.1f}%".format(lesion.get("coverage_pct", 0)),
            "",
            "Optic Disc/Cup:",
            "  Cup/Disc Ratio: " + "{:.2f}".format(optic.get("cup_disc_ratio", 0)),
            "",
            "Vessel Analysis:",
            "  Coverage: " + "{:.1f}%".format(vessel.get("coverage_pct", 0)),
        ]
        ds.TextValue = "\\n".join(lines)

        sr_path = tempfile.NamedTemporaryFile(suffix=".dcm", delete=False).name
        ds.save_as(sr_path)
        logger.info("DICOM SR saved to %s", sr_path)

        import requests
        with open(sr_path, "rb") as f:
            resp = requests.post("http://orthanc-container:8042/instances", data=f, headers={"Content-Type": "application/dicom"})
        logger.info("Pushed DICOM SR to Orthanc: %s", resp.status_code)
        os.unlink(sr_path)
    except Exception as e:
        logger.error("DICOM SR generation/push failed: %s", e)

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
                        # Inject correct StudyInstanceUID from source DICOMs
                        try:
                            dcm_files = list(pathlib.Path(image_path).glob("*"))
                            if dcm_files:
                                src_ds = dcmread(str(dcm_files[0]), stop_before_pixels=True)
                                if hasattr(src_ds, 'StudyInstanceUID'):
                                    seg_ds = dcmread(dicom_seg_file)
                                    seg_ds.StudyInstanceUID = src_ds.StudyInstanceUID
                                    seg_ds.save_as(dicom_seg_file)
                                    logger.info(f"Set SEG StudyInstanceUID: {src_ds.StudyInstanceUID}")
                        except Exception as e:
                            logger.warning(f"Could not set SEG StudyInstanceUID: {e}")
                        with open(dicom_seg_file, "rb") as f:'''
    new = '''                    # Read study_uid + patient_id from frontend params, inject into source DICOMs BEFORE SEG gen
                    source_study_uid = p.get("study_uid") or result.get("params", {}).get("study_uid")
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
    if old in content:
        content = content.replace(old, new)
        with open(INFER, "w") as f:
            f.write(content)
        print("infer.py: study_uid + patient_id injected into source DICOMs BEFORE SEG gen")
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
    import hashlib as _hl
    for _si, _sd in enumerate(image_datasets):
        if not hasattr(_sd, "FrameOfReferenceUID"):
            _sd.FrameOfReferenceUID = "2.25." + str(int(_hl.md5(str(_sd.SOPInstanceUID).encode()).hexdigest(), 16))[:39]
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
            _p10_valid_sops = {str(ds.SOPInstanceUID) for ds in image_datasets if hasattr(ds, "SOPInstanceUID")}
            _p10_sop_list = [str(ds.SOPInstanceUID) for ds in image_datasets if hasattr(ds, "SOPInstanceUID")}
            if _st or _sr or _p10_valid_sops:
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
                # Fix ReferencedSOPInstanceUID in ALL functional groups sequences.
                # Cornerstone3D reads both PerFrameFunctionalGroupsSequence AND
                # SharedFunctionalGroupsSequence.  Also handles ReferencedImageSequence
                # as a fallback path.
                if _p10_valid_sops:
                    # Validate frame count
                    if hasattr(_seg_fix, "PerFrameFunctionalGroupsSequence"):
                        _nf = len(_seg_fix.PerFrameFunctionalGroupsSequence)
                        _ns = len(_p10_sop_list)
                        if _nf != _ns:
                            logger.warning(
                                f"Frame count mismatch: SEG has {_nf} frames "
                                f"but source has {_ns} images"
                            )

                    def _fix_sop_ref_p10(_fg_item, _frame_idx, _sop_list, _uid_set):
                        _lm = False
                        # Path 1: DerivationImageSequence > SourceImageSequence
                        if hasattr(_fg_item, "DerivationImageSequence"):
                            for _d in _fg_item.DerivationImageSequence:
                                if hasattr(_d, "SourceImageSequence"):
                                    for _sr in _d.SourceImageSequence:
                                        if not hasattr(_sr, "ReferencedSOPInstanceUID"):
                                            continue
                                        _cu = str(_sr.ReferencedSOPInstanceUID)
                                        if _cu not in _uid_set:
                                            _rn = _sop_list[_frame_idx] if _frame_idx < len(_sop_list) else _sop_list[0]
                                            logger.warning(
                                                f"Frame {_frame_idx}: ReferencedSOPInstanceUID "
                                                f"{_cu[:60]}... not in source set -> patching to {_rn[:60]}..."
                                            )
                                            _sr.ReferencedSOPInstanceUID = _rn
                                            _lm = True
                        # Path 2: ReferencedImageSequence (direct)
                        if hasattr(_fg_item, "ReferencedImageSequence"):
                            for _sr in _fg_item.ReferencedImageSequence:
                                if not hasattr(_sr, "ReferencedSOPInstanceUID"):
                                    continue
                                _cu = str(_sr.ReferencedSOPInstanceUID)
                                if _cu not in _uid_set:
                                    _rn = _sop_list[_frame_idx] if _frame_idx < len(_sop_list) else _sop_list[0]
                                    logger.warning(
                                        f"Frame {_frame_idx} (ReferencedImageSequence): "
                                        f"ReferencedSOPInstanceUID {_cu[:60]}... -> patching to {_rn[:60]}..."
                                    )
                                    _sr.ReferencedSOPInstanceUID = _rn
                                    _lm = True
                        return _lm

                    # Fix PerFrameFunctionalGroupsSequence
                    if hasattr(_seg_fix, "PerFrameFunctionalGroupsSequence"):
                        for _p10_fi, _p10_fg in enumerate(_seg_fix.PerFrameFunctionalGroupsSequence):
                            if _fix_sop_ref_p10(_p10_fg, _p10_fi, _p10_sop_list, _p10_valid_sops):
                                _mod_fix = True

                    # Fix SharedFunctionalGroupsSequence
                    if hasattr(_seg_fix, "SharedFunctionalGroupsSequence"):
                        for _sfg in _seg_fix.SharedFunctionalGroupsSequence:
                            for _sfi in range(len(_p10_sop_list)):
                                if _fix_sop_ref_p10(_sfg, _sfi, _p10_sop_list, _p10_valid_sops):
                                    _mod_fix = True
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

if not patches_applied:
    print("No patches needed (already applied or versions mismatch)")
else:
    print("Patches applied successfully")
