import logging
import numpy as np
import hashlib
import json
import os
import tempfile
from pathlib import Path
from lib.infers.bigeye import quantify_lesion_mask

logger = logging.getLogger(__name__)

SEGMENTATION_MODELS = ["optic_disc_cup", "vessel_seg", "lesion_seg"]
CLIP_DR_MODEL = "clip_dr_classification"
LATERALITY_MODEL = "eye_laterality"


def run_segmentations(app, image_id):
    """Run all segmentation models and return the label file paths."""
    labels = {}
    for model_name in SEGMENTATION_MODELS:
        try:
            req = {
                "model": model_name,
                "image": image_id,
                "result_extension": ".nrrd",
                "result_dtype": "uint8",
                "restore_label_idx": False,
            }
            result = app.infer(req)
            if result and result.get("file") and os.path.exists(result["file"]):
                labels[model_name] = result["file"]
                logger.info(f"Segmentation {model_name} -> {result['file']}")
            else:
                logger.warning(f"Segmentation {model_name} returned no file")
        except Exception as e:
            logger.error(f"Segmentation {model_name} failed: {e}")
            if model_name == "lesion_seg":
                raise RuntimeError("BigEye lesion segmentation failed") from e
    return labels


def quantify_optic_disc_cup(label_path):
    """Compute cup/disc measurements and eye laterality from the NRRD mask."""
    try:
        import nrrd
        data, header = nrrd.read(label_path)
        if data.ndim == 3:
            data = data[0] if data.shape[0] == 1 else data.squeeze()
        disc_pixels = int(np.sum(data == 1))
        cup_pixels = int(np.sum(data == 2))
        ratio = cup_pixels / disc_pixels if disc_pixels > 0 else 0.0
        # La latéralité est déterminée par le modèle dédié eye_laterality (InceptionV3, 99.2%)
        # et non plus par la position du disque dans l'image.
        return {
            "disc_area_px": disc_pixels,
            "cup_area_px": cup_pixels,
            "cup_disc_ratio": round(ratio, 4),
            "disc_center_x": None,
            "laterality": "UNKNOWN",
        }
    except Exception as e:
        logger.error(f"quantify_optic_disc_cup failed: {e}")
        return {
            "disc_area_px": 0,
            "cup_area_px": 0,
            "cup_disc_ratio": 0.0,
            "disc_center_x": None,
            "laterality": "UNKNOWN",
        }


def quantify_vessels(label_path):
    """Compute vessel coverage and tortuosity from vessel segmentation NRRD."""
    try:
        import nrrd
        data, header = nrrd.read(label_path)
        if data.ndim == 3:
            data = data[0] if data.shape[0] == 1 else data.squeeze()
        total = int(data.size)
        vessel = int(np.sum(data > 0))
        coverage = (vessel / total * 100) if total > 0 else 0.0
        return {
            "coverage_pct": round(coverage, 2),
            "pixel_count": vessel,
        }
    except Exception as e:
        logger.error(f"quantify_vessels failed: {e}")
        return {"coverage_pct": 0.0, "pixel_count": 0}


def quantify_lesions(label_path):
    """Count connected lesion regions and retain their segmented pixel areas."""
    try:
        import cv2
        import nrrd
        data, header = nrrd.read(label_path)
        if data.ndim == 3:
            data = data[0] if data.shape[0] == 1 else data.squeeze()
        return quantify_lesion_mask(data)
    except Exception as e:
        logger.error(f"quantify_lesions failed: {e}")
        raise RuntimeError("BigEye lesion quantification failed") from e


def classify_dr(app, image_id):
    """Run the CLIP-DR classification model."""
    try:
        req = {
            "model": CLIP_DR_MODEL,
            "image": image_id,
            "result_extension": ".json",
            "restore_label_idx": False,
            "device": "cpu",
        }
        result = app.infer(req)
        if result and result.get("params"):
            params = result["params"]
            return {
                "status": params.get("status", "ok"),
                "grade": str(params.get("dr_label", "Unknown")),
                "grade_index": params.get("dr_grade"),
                "confidence": round(float(params.get("dr_probability", 0.0)), 4),
                "probabilities": params.get("dr_all_probabilities", {}),
                "calibration_status": params.get(
                    "calibration_status", "not_locally_calibrated"
                ),
                "model_id": params.get("model_id", "Qinkaiyu/CLIP-DR"),
            }
        logger.warning("CLIP-DR classification returned no params")
    except Exception as e:
        logger.error(f"CLIP-DR classification failed: {e}")
        return {
            "status": "unavailable",
            "grade": "Unknown",
            "confidence": 0.0,
            "probabilities": {},
            "calibration_status": "not_locally_calibrated",
            "reason": str(e),
        }
    return {
        "status": "unavailable",
        "grade": "Unknown",
        "confidence": 0.0,
        "probabilities": {},
        "calibration_status": "not_locally_calibrated",
    }


def classify_dr_models(app, image_id):
    """Run CLIP-DR as the sole diabetic-retinopathy classifier."""
    clip_dr = classify_dr(app, image_id)
    return clip_dr, {"clip_dr": clip_dr}, {}


def detect_laterality(app, image_id):
    """Run eye laterality classification model."""
    try:
        req = {
            "model": LATERALITY_MODEL,
            "image": image_id,
            "result_extension": ".json",
            "restore_label_idx": False,
        }
        result = app.infer(req)
        if result and result.get("params"):
            params = result["params"]
            laterality = params.get("laterality", "UNKNOWN")
            confidence = params.get("laterality_confidence", 0.0)
            probabilities = params.get("laterality_probabilities", {})
            return {
                "laterality": laterality,
                "confidence": round(float(confidence), 4),
                "probabilities": probabilities,
            }
        logger.warning("Eye laterality classification returned no params")
    except Exception as e:
        logger.error(f"Eye laterality classification failed: {e}")
    return {"laterality": "UNKNOWN", "confidence": 0.0, "probabilities": {}}


def update_dicom_image_laterality(orthanc_instance_id, laterality, orthanc_url="http://orthanc-container:8042"):
    """Update DICOM ImageLaterality (0022,0002) tag for an Orthanc instance."""
    import requests
    try:
        resp = requests.post(
            f"{orthanc_url}/instances/{orthanc_instance_id}/modify",
            json={"Replace": {"ImageLaterality": laterality}},
            timeout=30,
        )
        if resp.status_code == 200:
            logger.info(f"Set ImageLaterality={laterality} for instance {orthanc_instance_id}")
            requests.delete(f"{orthanc_url}/instances/{orthanc_instance_id}", timeout=15)
            return True
        logger.warning(f"Failed to set ImageLaterality: HTTP {resp.status_code}")
        return False
    except Exception as e:
        logger.error(f"Failed to update ImageLaterality: {e}")
        return False


def build_report(optic, vessel, lesion, dr, laterality=None):
    """Assemble the complete analysis report."""
    report = {
        "dr_classification": dr,
        "lesions": lesion,
        "optic_disc_cup": optic,
        "vessels": vessel,
    }
    if laterality and laterality.get("laterality") != "UNKNOWN":
        report["eye_laterality"] = laterality
    return report


def generate_dicom_sr(report, study_uid, series_uid, output_path):
    """Generate a DICOM SR document with the analysis report."""
    try:
        from pydicom import Dataset
        from pydicom.dataset import FileMetaDataset
        from pydicom.uid import generate_uid

        ds = Dataset()
        ds.FileMetaInformationGroupLength = 0
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
        ds.StudyDate = ""
        ds.SeriesDescription = "AI Ophthalmology Report"
        ds.Manufacturer = "OHIF + MONAI Label"
        ds.ManufacturerModelName = "AI Analysis Pipeline"

        ds.ContentDate = ""
        ds.ContentTime = ""
        ds.ReferencedPerformedProcedureStepSequence = ""

        dr = report.get("dr_classification", {})
        lesions = report.get("lesions", {})
        optic = report.get("optic_disc_cup", {})
        vessels = report.get("vessels", {})
        laterality = report.get("eye_laterality", {})

        lat_value = laterality.get("laterality", "")
        if lat_value in ("R", "L"):
            ds.ImageLaterality = lat_value

        text_lines = [
            "AI Ophthalmology Report",
            "",
            "Eye Laterality:",
            f"  Prediction: {lat_value if lat_value else 'N/A'}",
            f"  Confidence: {laterality.get('confidence', 0):.0%}",
            "",
            "DR Classification:",
            f"  Grade: {dr.get('grade', 'N/A')}",
            f"  Confidence: {dr.get('confidence', 0):.0%}",
            "",
            "Lesion Analysis:",
            f"  Microaneurysms: {lesions.get('microaneurysms', 0)}",
            f"  Hemorrhages: {lesions.get('hemorrhages', 0)}",
            f"  Exudates: {lesions.get('exudates', 0)}",
            f"  Coverage: {lesions.get('coverage_pct', 0):.1f}%",
            "",
            "Optic Disc/Cup:",
            f"  Disc Area: {optic.get('disc_area_px', 0)} px",
            f"  Cup Area: {optic.get('cup_area_px', 0)} px",
            f"  Cup/Disc Ratio: {optic.get('cup_disc_ratio', 0):.2f}",
            "",
            "Vessel Analysis:",
            f"  Coverage: {vessels.get('coverage_pct', 0):.1f}%",
            f"  Pixel Count: {vessels.get('pixel_count', 0)}",
        ]

        ds.TextValue = "\n".join(text_lines)

        ds.save_as(output_path)
        logger.info(f"DICOM SR saved to {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Failed to generate DICOM SR: {e}")
        return None


def push_to_orthanc(file_path, orthanc_url="http://orthanc-container:8042/instances"):
    """Push a DICOM file to Orthanc."""
    import requests
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(orthanc_url, data=f, headers={"Content-Type": "application/dicom"})
        logger.info(f"Pushed to Orthanc: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to push to Orthanc: {e}")
        return False
