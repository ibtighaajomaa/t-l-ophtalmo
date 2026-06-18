"""Apply patches to MONAI Label installed package for DICOM-SEG + Orthanc push."""
import os

CONVERT = "/usr/local/lib/python3.10/dist-packages/monailabel/datastore/utils/convert.py"
INFER = "/usr/local/lib/python3.10/dist-packages/monailabel/endpoints/infer.py"

patches_applied = False

# Patch 1: convert.py - synthetic geometry, FRUID hash, FRUID save/restore, mask dim fix
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
                new_fruid = "2.25." + hashlib.md5(str(ds.SOPInstanceUID).encode()).hexdigest()[:39]
                ds.FrameOfReferenceUID = new_fruid
                logger.info(f'Set FRUID on source: {new_fruid}')
            logger.info(f'SOP: {ds.SOPInstanceUID}')'''
    if old_read in content:
        content = content.replace(old_read, new_read)
        changes.append("convert.py: list comprehension + geometry injection + FRUID hash")
    else:
        print("WARNING: convert.py for-loop read pattern not found")

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
                                    src_full.FrameOfReferenceUID = "2.25." + hashlib.md5(str(src_full.SOPInstanceUID).encode()).hexdigest()[:39]
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
                                    src_full.FrameOfReferenceUID = "2.25." + hashlib.md5(str(src_full.SOPInstanceUID).encode()).hexdigest()[:39]
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
    import json, tempfile, os, pathlib, hashlib, numpy as np
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

    # ---- Segmentations ----
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

    # ---- Quantify Optic Disc/Cup ----
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

    # ---- Quantify Vessels ----
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

    # ---- Quantify Lesions ----
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

    # ---- DR Classification ----
    dr = {"grade": "Unknown", "confidence": 0.0}
    try:
        r = instance.infer({"model": "dr_classification", "image": image})
        if r:
            p = r.get("params", {})
            grade = p.get("label", p.get("prediction", "Unknown"))
            conf = p.get("probability", p.get("confidence", 0.0))
            if isinstance(conf, (list, np.ndarray)):
                conf = float(max(conf))
            if isinstance(grade, list):
                top = max(grade, key=lambda x: x.get("score", 0) if isinstance(x, dict) else 0)
                grade = top.get("label", str(grade)) if isinstance(top, dict) else str(grade)
                conf = top.get("score", conf) if isinstance(top, dict) else conf
            if not grade or grade == "Unknown":
                for key in ["grade", "label", "prediction", "class"]:
                    val = r.get(key)
                    if val:
                        grade = str(val)
                        break
            dr = {"grade": str(grade), "confidence": round(float(conf), 4)}
    except Exception as e:
        logger.error("DR classification failed: %s", e)

    # ---- Build Report ----
    report = {
        "dr_classification": dr,
        "lesions": lesion,
        "optic_disc_cup": optic,
        "vessels": vessel,
    }

    # ---- DICOM SR + Orthanc Push ----
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

        # Push to Orthanc
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
            print("infer.py: inserted /infer/analyze endpoint BEFORE /{model} catch-all")
            patches_applied = True
        else:
            print("WARNING: Could not find /{model} route in infer.py to insert analyze endpoint")

if not patches_applied:
    print("No patches needed (already applied or versions mismatch)")
else:
    print("Patches applied successfully")
