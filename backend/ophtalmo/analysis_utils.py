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

DR_MODEL_NAMES = {
    "clip_dr": "CLIP-DR",
}
DR_MODEL_PRIORITY = {"clip_dr": 0}


def _dr_grade_index(result):
    """Return the normalized ordinal DR grade for one model result."""
    if not isinstance(result, dict):
        return -1
    try:
        explicit = result.get("grade_index")
        if explicit is not None and 0 <= int(explicit) <= 4:
            return int(explicit)
    except (TypeError, ValueError):
        pass
    grade = str(result.get("grade") or result.get("label") or "unknown")
    normalized = grade.strip().lower().replace("_", " ").replace("-", " ")
    for marker, index in (
        ("proliferative", 4),
        ("severe", 3),
        ("moderate", 2),
        ("mild", 1),
        ("no dr", 0),
        ("normal", 0),
    ):
        if marker in normalized:
            return index
    return -1


DR_GRADE_KEYS = ["no_dr", "mild_npdr", "moderate_npdr", "severe_npdr", "proliferative_dr"]
DR_GRADE_LABELS_FR = {
    "no_dr": "Pas de RD",
    "mild_npdr": "RDNP légère",
    "moderate_npdr": "RDNP modérée",
    "severe_npdr": "RDNP sévère",
    "proliferative_dr": "RD proliférante",
}
_DR_GRADE_ALIASES = {
    "normal": "no_dr", "no dr": "no_dr", "nodr": "no_dr", "0": "no_dr",
    "mild": "mild_npdr", "mild npdr": "mild_npdr", "1": "mild_npdr",
    "moderate": "moderate_npdr", "moderate npdr": "moderate_npdr", "2": "moderate_npdr",
    "severe": "severe_npdr", "severe npdr": "severe_npdr", "3": "severe_npdr",
    "proliferative": "proliferative_dr", "proliferative dr": "proliferative_dr",
    "pdr": "proliferative_dr", "4": "proliferative_dr",
}


def normalize_dr_grade(value):
    """Return the canonical DR grade key for a label, alias or index, else None."""
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_")
    if text in DR_GRADE_KEYS:
        return text
    spaced = text.replace("_", " ")
    return _DR_GRADE_ALIASES.get(spaced) or _DR_GRADE_ALIASES.get(text)


def ai_dr_classification(eye):
    """AI-side classification of one eye, ignoring any doctor-derived adjudication."""
    if not isinstance(eye, dict):
        return {}
    adjudication = eye.get("medgemma_dr_adjudication")
    if isinstance(adjudication, dict) and adjudication.get("method") == "doctor_correction":
        adjudication = None
    return (
        adjudication
        or eye.get("selected_dr_classification")
        or eye.get("dr_classification")
        or {}
    )


def effective_dr_classification(eye):
    """Doctor-corrected grade when present, otherwise the AI classification."""
    if not isinstance(eye, dict):
        return {}
    correction = eye.get("doctor_dr_correction")
    grade = normalize_dr_grade(correction.get("grade")) if isinstance(correction, dict) else None
    if grade:
        return {
            "grade": grade,
            "grade_index": DR_GRADE_KEYS.index(grade),
            "label_fr": DR_GRADE_LABELS_FR[grade],
            "confidence": 1.0,
            "source": "doctor",
            "doctor_corrected": True,
        }
    return ai_dr_classification(eye)


DEEPSEENET_FACTORS = {
    "drusen": ("none_small", "intermediate", "large"),
    "pigment": ("absent", "present"),
    "amd": ("absent", "advanced"),
}
DEEPSEENET_LABELS_FR = {
    "drusen": {"none_small": "Absents / petits", "intermediate": "Intermédiaires", "large": "Larges"},
    "pigment": {"absent": "Absentes", "present": "Présentes"},
    "amd": {"absent": "Absente", "advanced": "Présente"},
}


def normalize_deepseenet_label(factor, value):
    """Canonical DeepSeeNet+ label for a factor, or None when unsupported."""
    labels = DEEPSEENET_FACTORS.get(factor)
    if not labels or value is None:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "none": "none_small", "small": "none_small", "no": "absent", "yes": "present",
        "present_amd": "advanced", "advanced_amd": "advanced",
    }
    text = aliases.get(text, text)
    if text.isdigit():
        index = int(text)
        return labels[index] if 0 <= index < len(labels) else None
    return text if text in labels else None


def effective_deepseenet_factor(deepseenet, factor):
    """Doctor-corrected value of one DMLA factor when present, else the AI prediction."""
    if not isinstance(deepseenet, dict):
        return {}
    corrections = deepseenet.get("doctor_corrections")
    correction = corrections.get(factor) if isinstance(corrections, dict) else None
    label = normalize_deepseenet_label(factor, correction.get("label")) if isinstance(correction, dict) else None
    if label:
        return {
            "label": label,
            "class_index": DEEPSEENET_FACTORS[factor].index(label),
            "probability": 1.0,
            "source": "doctor",
            "doctor_corrected": True,
        }
    prediction = deepseenet.get(factor)
    return dict(prediction) if isinstance(prediction, dict) else {}


def select_critical_dr_classification(models):
    """Select the highest main grade, using confidence only as a tie-breaker."""
    available = []
    for model_key, model_result in (models or {}).items():
        if not isinstance(model_result, dict) or model_result.get("status") != "ok":
            continue
        grade_index = _dr_grade_index(model_result)
        if grade_index < 0:
            continue
        try:
            confidence = float(model_result.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        available.append((model_key, model_result, grade_index, confidence))

    if not available:
        return None

    selected_key, selected, selected_grade, confidence = max(
        available,
        key=lambda item: (
            item[2],
            item[3],
            -DR_MODEL_PRIORITY.get(item[0], len(DR_MODEL_PRIORITY)),
        ),
    )
    grade_indexes = [item[2] for item in available]
    spread = max(grade_indexes) - min(grade_indexes)
    return {
        "status": "ok",
        "model_key": selected_key,
        "model_name": DR_MODEL_NAMES.get(selected_key, selected_key),
        "grade": selected.get("grade") or "Unknown",
        "grade_index": selected_grade,
        "confidence": confidence,
        "probabilities": selected.get("probabilities") or {},
        "calibration_status": selected.get("calibration_status"),
        "selection_method": "highest_predicted_grade_then_confidence",
        "model_grade_spread": spread,
        "requires_review": spread >= 2,
    }


def select_closest_dr_model(models, adjudication):
    """Select the model closest to MedGemma; prefer severity, then confidence."""
    if not isinstance(adjudication, dict):
        return None
    target_grade = _dr_grade_index(adjudication)
    if target_grade < 0:
        return None
    candidates = []
    for model_key, model_result in (models or {}).items():
        if not isinstance(model_result, dict) or model_result.get("status") != "ok":
            continue
        grade_index = _dr_grade_index(model_result)
        if grade_index < 0:
            continue
        try:
            confidence = float(model_result.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        candidates.append((model_key, model_result, grade_index, confidence))
    if not candidates:
        return None
    model_key, model_result, grade_index, confidence = min(
        candidates,
        key=lambda item: (
            abs(item[2] - target_grade),
            -item[2],
            -item[3],
            DR_MODEL_PRIORITY.get(item[0], len(DR_MODEL_PRIORITY)),
        ),
    )
    distance = abs(grade_index - target_grade)
    return {
        "model_key": model_key,
        "model_name": DR_MODEL_NAMES.get(model_key, model_key),
        "grade": model_result.get("grade") or "Unknown",
        "grade_index": grade_index,
        "confidence": confidence,
        "probabilities": model_result.get("probabilities") or {},
        "calibration_status": model_result.get("calibration_status"),
        "distance_from_medgemma_grade": distance,
        "exact_grade_match": distance == 0,
        "selection_method": "closest_to_medgemma_then_severity_then_confidence",
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
    return _dr_grade_index(dr)


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
        "selected_dr_classification": None,
        "medgemma_dr_adjudication": None,
        "closest_dr_model": None,
        "lesions": {
            "microaneurysms": 0,
            "hemorrhages": 0,
            "hard_exudates": 0,
            "soft_exudates": 0,
            "cotton_wool_spots": 0,
            "neovascularization": 0,
            "laser_scars": 0,
            "exudates": 0,
            "pixel_counts": {
                "microaneurysms": 0,
                "hemorrhages": 0,
                "hard_exudates": 0,
                "soft_exudates": 0,
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
    incoming_models = report.get("dr_classification_models") or {}
    target["dr_classification_models"] = {
        key: value for key, value in incoming_models.items() if key != "vit"
    } or target["dr_classification_models"]
    target["selected_dr_classification"] = select_critical_dr_classification(
        target["dr_classification_models"]
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
        effective = effective_deepseenet_factor(prediction, factor)
        try:
            return int(effective.get("class_index", -1))
        except (TypeError, ValueError):
            return -1

    doctor_corrected = any(
        isinstance(dsn, dict) and isinstance(dsn.get("doctor_corrections"), dict) and dsn["doctor_corrections"]
        for dsn in (left_dsn, right_dsn)
    )

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
        "doctor_corrected": doctor_corrected,
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
            soft_exudates = int(
                src.get("soft_exudates")
                if src.get("soft_exudates") is not None
                else src.get("cotton_wool_spots") or 0
            )
            lesions["hard_exudates"] += hard_exudates
            lesions["soft_exudates"] += soft_exudates
            lesions["cotton_wool_spots"] += soft_exudates
            lesions["neovascularization"] += int(src.get("neovascularization") or 0)
            lesions["laser_scars"] += int(src.get("laser_scars") or 0)
            # Old reports only contain the aggregate `exudates` field.
            lesions["exudates"] += (
                hard_exudates + soft_exudates
                if "hard_exudates" in src or "soft_exudates" in src or "cotton_wool_spots" in src
                else int(src.get("exudates") or 0)
            )
            src_pixels = src.get("pixel_counts") or {}
            for lesion_name in lesions["pixel_counts"]:
                if lesion_name in {"soft_exudates", "cotton_wool_spots"}:
                    continue
                lesions["pixel_counts"][lesion_name] += int(src_pixels.get(lesion_name) or 0)
            soft_exudate_pixels = int(
                src_pixels.get("soft_exudates")
                if src_pixels.get("soft_exudates") is not None
                else src_pixels.get("cotton_wool_spots") or 0
            )
            lesions["pixel_counts"]["soft_exudates"] += soft_exudate_pixels
            lesions["pixel_counts"]["cotton_wool_spots"] += soft_exudate_pixels
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
        if not isinstance(eye, dict):
            continue
        effective = effective_dr_classification(eye)
        dr = effective if effective.get("source") == "doctor" else (eye.get("dr_classification") or {})
        try:
            confidences.append(float(dr.get("confidence")))
        except (TypeError, ValueError):
            pass
    return min(confidences) if confidences else None
