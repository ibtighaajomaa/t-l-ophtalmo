from ophtalmo.analysis_utils import (
    _blank_eye,
    _copy_report_fields,
    select_critical_dr_classification,
)


def test_legacy_report_keeps_comparison_models_unavailable():
    eye = _blank_eye("right")
    _copy_report_fields(
        eye,
        {
            "dr_classification": {
                "grade": "Moderate NPDR",
                "confidence": 0.8,
                "probabilities": {},
            }
        },
    )

    assert eye["dr_classification"]["grade"] == "Moderate NPDR"
    assert eye["dr_classification_models"]["vit"]["status"] == "unavailable"
    assert eye["dr_classification_models"]["clip_dr"]["status"] == "unavailable"
    assert eye["dr_classification_models"]["flair"]["status"] == "unavailable"
    assert set(eye["dr_classification_models"]) == {"vit", "clip_dr", "flair"}


def test_clip_dr_report_is_propagated():
    eye = _blank_eye("left")
    report = {
        "dr_classification": {
            "grade": "Mild NPDR",
            "confidence": 0.75,
            "probabilities": {},
        },
        "dr_classification_models": {
            "vit": {
                "status": "ok",
                "grade": "Mild NPDR",
                "grade_index": 1,
                "confidence": 0.75,
                "probabilities": {},
                "calibration_status": "not_locally_calibrated",
            },
            "clip_dr": {
                "status": "ok",
                "grade": "Severe NPDR",
                "grade_index": 3,
                "confidence": 0.7,
                "probabilities": {},
                "calibration_status": "not_locally_calibrated",
            },
            "flair": {
                "status": "ok",
                "grade": "Moderate NPDR",
                "grade_index": 2,
                "confidence": 0.6,
                "probabilities": {},
                "calibration_status": "not_locally_calibrated",
            },
        },
    }

    _copy_report_fields(eye, report)

    assert eye["dr_classification"] == report["dr_classification"]
    assert eye["dr_classification_models"] == report["dr_classification_models"]
    assert eye["selected_dr_classification"]["model_key"] == "clip_dr"
    assert eye["selected_dr_classification"]["grade_index"] == 3


def _model(grade_index, confidence, status="ok"):
    grades = ["no_dr", "mild_npdr", "moderate_npdr", "severe_npdr", "proliferative_dr"]
    return {
        "status": status,
        "grade": grades[grade_index],
        "grade_index": grade_index,
        "confidence": confidence,
        "probabilities": {grades[grade_index]: confidence},
    }


def test_selects_highest_grade_before_confidence():
    selected = select_critical_dr_classification({
        "vit": _model(2, 0.46),
        "clip_dr": _model(1, 0.65),
        "flair": _model(0, 0.58),
    })
    assert selected["model_key"] == "vit"
    assert selected["grade_index"] == 2
    assert selected["model_grade_spread"] == 2
    assert selected["requires_review"] is True


def test_confidence_breaks_same_grade_tie():
    selected = select_critical_dr_classification({
        "vit": _model(2, 0.46),
        "clip_dr": _model(2, 0.71),
        "flair": _model(1, 0.80),
    })
    assert selected["model_key"] == "clip_dr"
    assert selected["confidence"] == 0.71


def test_unavailable_model_is_excluded():
    selected = select_critical_dr_classification({
        "vit": _model(4, 0.99, status="unavailable"),
        "clip_dr": _model(1, 0.60),
    })
    assert selected["model_key"] == "clip_dr"
