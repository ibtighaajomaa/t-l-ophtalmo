DR_SEVERITY = {
    "unknown": -1,
    "no dr": 0,
    "normal": 0,
    "mild": 1,
    "mild dr": 1,
    "moderate": 2,
    "moderate dr": 2,
    "severe": 3,
    "severe dr": 3,
    "proliferative": 4,
    "proliferative dr": 4,
    "pdr": 4,
}

GLAUCOMA_RISK = {
    "n/a": -1,
    "faible": 0,
    "modere": 1,
    "modéré": 1,
    "eleve": 2,
    "élevé": 2,
    "tres eleve": 3,
    "très élevé": 3,
}


def side_from_laterality(value):
    if isinstance(value, dict):
        value = (
            value.get("laterality")
            or value.get("eye_laterality")
            or value.get("side")
            or value.get("label")
        )
    if not value:
        return None
    v = str(value).strip().lower()
    if v in {"r", "right", "od", "droit", "oeil droit", "œil droit"}:
        return "right"
    if v in {"l", "left", "os", "og", "gauche", "oeil gauche", "œil gauche"}:
        return "left"
    return None


def _dr_score(report):
    dr = report.get("dr_classification") or {}
    grade = str(dr.get("grade") or dr.get("label") or "Unknown").strip().lower()
    return DR_SEVERITY.get(grade, -1)


def _glaucoma_score(report):
    glaucoma = report.get("glaucoma") or {}
    risk = str(glaucoma.get("risk") or "N/A").strip().lower()
    return (float(glaucoma.get("vcdr") or 0), GLAUCOMA_RISK.get(risk, -1))


def _blank_eye(side):
    return {
        "side": side,
        "series_instance_uids": [],
        "dr_classification": {
            "grade": "Unknown",
            "confidence": 0.0,
            "probabilities": [],
        },
        "dr_classification_models": {
            "clip_dr": {
                "status": "unavailable",
                "grade": "Unknown",
                "confidence": 0.0,
                "probabilities": [],
                "calibration_status": "not_locally_calibrated",
            },
        },
        "lesions": {
            "microaneurysms": 0,
            "hemorrhages": 0,
            "hard_exudates": 0,
            "cotton_wool_spots": 0,
            "neovascularization": 0,
            "laser_scars": 0,
            "exudates": 0,
            "pixel_counts": {
                "microaneurysms": 0,
                "hemorrhages": 0,
                "hard_exudates": 0,
                "cotton_wool_spots": 0,
                "neovascularization": 0,
                "laser_scars": 0,
            },
            "coverage_pct": 0.0,
        },
        "optic_disc_cup": {
            "disc_area_px": 0,
            "cup_area_px": 0,
            "cup_disc_ratio": 0.0,
        },
        "glaucoma": {
            "vcdr": 0.0,
            "risk": "N/A",
            "disc_area_px": 0,
            "cup_area_px": 0,
        },
        "vessels": {
            "coverage_pct": 0.0,
            "pixel_count": 0,
        },
        "fovea": None,
        "deepseenet_plus": None,
        "gradcam_image": None,
        "clahe_image": None,
        "visual_source": None,
        "source_series_uid": None,
    }


def _copy_report_fields(target, report, include_visuals=True):
    target["dr_classification"] = report.get("dr_classification") or target["dr_classification"]
    target["dr_classification_models"] = (
        report.get("dr_classification_models") or target["dr_classification_models"]
    )
    target["optic_disc_cup"] = report.get("optic_disc_cup") or target["optic_disc_cup"]
    target["glaucoma"] = report.get("glaucoma") or target["glaucoma"]
    target["vessels"] = report.get("vessels") or target["vessels"]
    target["fovea"] = report.get("fovea") or target.get("fovea")
    if include_visuals:
        target["gradcam_image"] = report.get("gradcam_image")
        target["clahe_image"] = report.get("clahe_image")


def aggregate_critical_deepseenet(items):
    """Keep the most severe prediction for each factor across one eye.

    Factors may intentionally originate from different images. Source SOP and
    preprocessing metadata remain attached for clinical traceability.
    """
    candidates = []
    for series_uid, report in items:
        prediction = report.get("deepseenet_plus")
        if not isinstance(prediction, dict) or prediction.get("status") not in {"ok", "ok_with_fallback"}:
            continue
        source = report.get("source") or {}
        candidates.append((series_uid, source, prediction))
    if not candidates:
        return None

    result = {
        "status": "ok",
        "aggregation": "most_critical_per_factor",
        "conservative": True,
        "note": "Risk factors may originate from different images of the same eye.",
    }
    for factor in ("drusen", "pigment", "amd"):
        available = [item for item in candidates if isinstance(item[2].get(factor), dict)]
        if not available:
            continue
        series_uid, source, prediction = max(
            available,
            key=lambda item: (
                int(item[2][factor].get("class_index", -1)),
                float(item[2][factor].get("probability", 0)),
            ),
        )
        selected = dict(prediction[factor])
        selected["source_sop_instance_uid"] = (
            prediction.get("source_sop_instance_uid")
            or source.get("source_sop_instance_uid")
        )
        selected["source_series_uid"] = source.get("series_instance_uid") or series_uid.split(":", 1)[0]
        selected["preprocessing_mode"] = prediction.get("preprocessing_mode")
        selected["fovea"] = prediction.get("fovea")
        result[factor] = selected
    return result


def calculate_deepseenet_patient_score(per_eye):
    left = (per_eye or {}).get("left") or {}
    right = (per_eye or {}).get("right") or {}
    left_dsn = left.get("deepseenet_plus")
    right_dsn = right.get("deepseenet_plus")
    if not left_dsn or not right_dsn:
        return {
            "simplified_score": None,
            "score_status": "bilateral_input_missing",
            "aggregation": "most_critical_per_factor",
        }

    def index(prediction, factor):
        return int((prediction.get(factor) or {}).get("class_index", -1))

    # Any advanced AMD fixes the simplified severity score at its maximum.
    if index(left_dsn, "amd") == 1 or index(right_dsn, "amd") == 1:
        score = 5
    else:
        score = 0
        score += int(index(left_dsn, "pigment") == 1)
        score += int(index(right_dsn, "pigment") == 1)
        score += int(index(left_dsn, "drusen") == 2)
        score += int(index(right_dsn, "drusen") == 2)
        score += int(index(left_dsn, "drusen") == 1 and index(right_dsn, "drusen") == 1)
        score = min(score, 5)
    return {
        "simplified_score": score,
        "score_status": "complete",
        "aggregation": "most_critical_per_factor",
    }


def _report_sop_uid(series_uid, report):
    source = report.get("source") or {}
    sop_uid = source.get("source_sop_instance_uid")
    if sop_uid:
        return sop_uid
    if isinstance(series_uid, str) and ":" in series_uid:
        return series_uid.rsplit(":", 1)[-1]
    return None


def _quality_score(series_uid, report, quality_scores):
    sop_uid = _report_sop_uid(series_uid, report)
    if sop_uid and quality_scores and sop_uid in quality_scores:
        try:
            return float(quality_scores[sop_uid])
        except (TypeError, ValueError):
            pass
    return -1.0


def aggregate_per_eye(per_series, quality_scores=None):
    grouped = {}
    for series_uid, report in (per_series or {}).items():
        if not isinstance(report, dict):
            continue
        side = (
            side_from_laterality(report.get("eye_laterality"))
            or side_from_laterality((report.get("optic_disc_cup") or {}).get("laterality"))
            or side_from_laterality((report.get("source") or {}).get("laterality"))
        )
        if not side:
            continue
        grouped.setdefault(side, []).append((series_uid, report))

    result = {}
    for side, items in grouped.items():
        eye = _blank_eye(side)
        eye["series_instance_uids"] = [series_uid for series_uid, _ in items]

        worst_dr_uid, worst_dr = max(items, key=lambda item: _dr_score(item[1]))
        eye["source_series_uid"] = worst_dr_uid
        _copy_report_fields(eye, worst_dr, include_visuals=False)

        visual_uid, visual_report = max(
            items,
            key=lambda item: (
                _quality_score(item[0], item[1], quality_scores),
                1 if item[1].get("gradcam_image") or item[1].get("clahe_image") else 0,
            ),
        )
        eye["gradcam_image"] = visual_report.get("gradcam_image")
        eye["clahe_image"] = visual_report.get("clahe_image")
        eye["visual_source"] = {
            "series_report_key": visual_uid,
            "series_instance_uid": (visual_report.get("source") or {}).get("series_instance_uid"),
            "sop_instance_uid": _report_sop_uid(visual_uid, visual_report),
            "quality_score": _quality_score(visual_uid, visual_report, quality_scores),
        }
        eye["fovea"] = visual_report.get("fovea")
        eye["deepseenet_plus"] = aggregate_critical_deepseenet(items)

        _, worst_glaucoma = max(items, key=lambda item: _glaucoma_score(item[1]))
        eye["glaucoma"] = worst_glaucoma.get("glaucoma") or eye["glaucoma"]
        eye["optic_disc_cup"] = worst_glaucoma.get("optic_disc_cup") or eye["optic_disc_cup"]

        _, worst_vessels = max(
            items,
            key=lambda item: float((item[1].get("vessels") or {}).get("coverage_pct") or 0),
        )
        eye["vessels"] = worst_vessels.get("vessels") or eye["vessels"]

        lesions = eye["lesions"].copy()
        lesions["pixel_counts"] = lesions["pixel_counts"].copy()
        for _, report in items:
            src = report.get("lesions") or {}
            lesions["microaneurysms"] += int(src.get("microaneurysms") or 0)
            lesions["hemorrhages"] += int(src.get("hemorrhages") or 0)
            hard_exudates = int(src.get("hard_exudates") or 0)
            cotton_wool_spots = int(src.get("cotton_wool_spots") or 0)
            lesions["hard_exudates"] += hard_exudates
            lesions["cotton_wool_spots"] += cotton_wool_spots
            lesions["neovascularization"] += int(src.get("neovascularization") or 0)
            lesions["laser_scars"] += int(src.get("laser_scars") or 0)
            # Old reports only contain the aggregate `exudates` field.
            lesions["exudates"] += (
                hard_exudates + cotton_wool_spots
                if "hard_exudates" in src or "cotton_wool_spots" in src
                else int(src.get("exudates") or 0)
            )
            src_pixels = src.get("pixel_counts") or {}
            for lesion_name in lesions["pixel_counts"]:
                lesions["pixel_counts"][lesion_name] += int(src_pixels.get(lesion_name) or 0)
            lesions["coverage_pct"] = max(
                float(lesions.get("coverage_pct") or 0),
                float(src.get("coverage_pct") or 0),
            )
        eye["lesions"] = lesions
        result[side] = eye

    return result


def worst_dr_confidence(per_eye):
    confidences = []
    for eye in (per_eye or {}).values():
        dr = eye.get("dr_classification") or {}
        try:
            confidences.append(float(dr.get("confidence")))
        except (TypeError, ValueError):
            pass
    return min(confidences) if confidences else None
