"""Patch installed MONAI Label /infer/analyze for single-instance OP analysis."""

from pathlib import Path


INFER = Path("/usr/local/lib/python3.10/dist-packages/monailabel/endpoints/infer.py")


ANALYZE_CODE = '''### ANALYZE_ENDPOINT ###
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
        hard_exudates = _regions(3)
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
            "classification_method", "zero_shot_prompts", "domain_knowledge_prompts",
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
    label_infos = {}
    for model in ("optic_disc_cup", "vessel_seg", "lesion_seg", "neovascularization_seg"):
        try:
            result = _run_model(model)
            path = result.get("file") or result.get("label")
            if path and os.path.exists(path):
                labels[model] = path
                label_info = (result.get("params") or {}).get("label_info")
                if label_info:
                    label_infos[model] = label_info
                logger.info("Analyze segmentation %s -> %s", model, path)
            else:
                logger.warning("Analyze segmentation %s returned no label file", model)
        except Exception as e:
            logger.error("Analyze segmentation %s failed: %s", model, e)

    # Persist the generated masks as DICOM-SEG objects so OHIF can discover and
    # display them.  instance.infer() only returns temporary NRRD files.
    if labels and request.get("push_dicom_seg", True):
        try:
            import copy
            import requests
            from monailabel.datastore.utils.convert import nifti_to_dicom_seg

            image_uri = datastore.get_image_uri(image)
            image_path = next(
                (image_uri[:-len(suffix)] for suffix in (".nii.gz", ".nii", ".nrrd") if image_uri.endswith(suffix)),
                image_uri,
            )
            if image_path and os.path.isdir(image_path):
                for model, result_image in labels.items():
                    label_info = copy.deepcopy(label_infos.get(model))
                    if not label_info:
                        logger.warning("Analyze DICOM-SEG skipped for %s: missing label_info", model)
                        continue
                    if isinstance(label_info, list):
                        for segment in label_info:
                            if isinstance(segment, dict):
                                segment["model_name"] = model
                    try:
                        dicom_seg_file = nifti_to_dicom_seg(
                            image_path, result_image, label_info, use_itk=False
                        )
                        if dicom_seg_file and os.path.exists(dicom_seg_file):
                            with open(dicom_seg_file, "rb") as stream:
                                response = requests.post(
                                    "http://orthanc-container:8042/instances",
                                    data=stream,
                                    headers={"Content-Type": "application/dicom"},
                                    timeout=60,
                                )
                            response.raise_for_status()
                            logger.info("Pushed DICOM-SEG to Orthanc from analyze/%s: %s", model, response.status_code)
                            os.unlink(dicom_seg_file)
                        else:
                            logger.info("Analyze DICOM-SEG not created for %s (empty mask)", model)
                    except Exception as push_error:
                        logger.error("Analyze DICOM-SEG push failed for %s: %s", model, push_error)
            else:
                logger.warning("Analyze DICOM-SEG source directory not found: %s", image_path)
        except Exception as push_error:
            logger.error("Analyze DICOM-SEG export failed: %s", push_error)

    vit_dr = {
        "status": "unavailable",
        "grade": "Unknown",
        "confidence": 0.0,
        "probabilities": {},
        "calibration_status": "not_locally_calibrated",
    }
    try:
        vit_result = _run_model(
            "dr_classification",
            {"result_extension": ".json", "device": "cpu"},
        )
        vit_dr = _normalize_dr(vit_result.get("params") or {})
        vit_dr.setdefault("status", "ok")
        vit_dr.setdefault("model_id", "Kontawat/vit-diabetic-retinopathy-classification")
        vit_dr.setdefault("calibration_status", "not_locally_calibrated")
    except Exception as e:
        logger.warning("Analyze ViT DR unavailable: %s", e)
        vit_dr["reason"] = str(e)[:240]

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

    # ViT remains canonical; CLIP-DR is an independent comparator.
    dr = vit_dr
    dr_classification_models = {"vit": vit_dr, "clip_dr": clip_dr}

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
    slice_result = {
        "index": 0,
        "source_sop_instance_uid": source_sop_uid,
        "dr_classification": dr,
        "dr_classification_models": dr_classification_models,
        "optic_disc_cup": optic,
        "glaucoma": glaucoma,
        "vessels": vessels,
        "lesions": lesions,
        "severity_score": _severity(dr, glaucoma),
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
        "gradcam_image": None,
        "clahe_image": None,
        "per_instance": [slice_result],
        "critical": {
            "od": slice_result if optic.get("laterality") == "OD" else None,
            "os": slice_result if optic.get("laterality") == "OS" else None,
        },
    }

'''


def main():
    content = INFER.read_text()
    start = content.find("### ANALYZE_ENDPOINT ###")
    end = content.find('@router.post("/{model}"', start)
    if start < 0 or end <= start:
        raise SystemExit("analyze endpoint boundaries not found")
    INFER.write_text(content[:start] + ANALYZE_CODE + content[end:])
    print("patched analyze endpoint")


if __name__ == "__main__":
    main()
