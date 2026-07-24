from ophtalmo.analysis_utils import _blank_eye, _copy_report_fields


def test_legacy_report_keeps_canonical_dr_and_clip_unavailable():
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
    assert eye["dr_classification_models"]["clip_dr"]["status"] == "unavailable"
    assert eye["dr_model_comparison"]["concordant"] is None


def test_dual_report_is_propagated_without_changing_canonical_result():
    eye = _blank_eye("left")
    report = {
        "dr_classification": {
            "grade": "Mild NPDR",
            "confidence": 0.75,
            "probabilities": {},
        },
        "dr_classification_models": {
            "vit_current": {
                "status": "ok",
                "grade": "Mild NPDR",
                "grade_index": 1,
                "confidence": 0.75,
                "probabilities": {},
            },
            "clip_dr": {
                "status": "ok",
                "grade": "Severe NPDR",
                "grade_index": 3,
                "confidence": 0.7,
                "probabilities": {},
                "calibration_status": "not_locally_calibrated",
            },
        },
        "dr_model_comparison": {"concordant": False, "grade_difference": 2},
    }

    _copy_report_fields(eye, report)

    assert eye["dr_classification"] == report["dr_classification"]
    assert eye["dr_classification_models"] == report["dr_classification_models"]
    assert eye["dr_model_comparison"] == {"concordant": False, "grade_difference": 2}
