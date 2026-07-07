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
        "lesions": {
            "microaneurysms": 0,
            "hemorrhages": 0,
            "exudates": 0,
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
        "gradcam_image": None,
        "clahe_image": None,
        "source_series_uid": None,
    }


def _copy_report_fields(target, report):
    target["dr_classification"] = report.get("dr_classification") or target["dr_classification"]
    target["optic_disc_cup"] = report.get("optic_disc_cup") or target["optic_disc_cup"]
    target["glaucoma"] = report.get("glaucoma") or target["glaucoma"]
    target["vessels"] = report.get("vessels") or target["vessels"]
    target["gradcam_image"] = report.get("gradcam_image")
    target["clahe_image"] = report.get("clahe_image")


def aggregate_per_eye(per_series):
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
        _copy_report_fields(eye, worst_dr)

        _, worst_glaucoma = max(items, key=lambda item: _glaucoma_score(item[1]))
        eye["glaucoma"] = worst_glaucoma.get("glaucoma") or eye["glaucoma"]
        eye["optic_disc_cup"] = worst_glaucoma.get("optic_disc_cup") or eye["optic_disc_cup"]

        _, worst_vessels = max(
            items,
            key=lambda item: float((item[1].get("vessels") or {}).get("coverage_pct") or 0),
        )
        eye["vessels"] = worst_vessels.get("vessels") or eye["vessels"]

        lesions = eye["lesions"].copy()
        for _, report in items:
            src = report.get("lesions") or {}
            lesions["microaneurysms"] += int(src.get("microaneurysms") or 0)
            lesions["hemorrhages"] += int(src.get("hemorrhages") or 0)
            lesions["exudates"] += int(src.get("exudates") or 0)
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
