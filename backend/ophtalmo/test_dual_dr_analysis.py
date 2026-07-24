from ophtalmo.analysis_utils import _blank_eye, _copy_report_fields


def test_legacy_report_keeps_dr_and_clip_unavailable():
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
    assert set(eye["dr_classification_models"]) == {"clip_dr"}


def test_clip_dr_report_is_propagated():
    eye = _blank_eye("left")
    report = {
        "dr_classification": {
            "grade": "Mild NPDR",
            "confidence": 0.75,
            "probabilities": {},
        },
        "dr_classification_models": {
            "clip_dr": {
                "status": "ok",
                "grade": "Severe NPDR",
                "grade_index": 3,
                "confidence": 0.7,
                "probabilities": {},
                "calibration_status": "not_locally_calibrated",
            },
        },
    }

    _copy_report_fields(eye, report)

    assert eye["dr_classification"] == report["dr_classification"]
    assert eye["dr_classification_models"] == report["dr_classification_models"]
