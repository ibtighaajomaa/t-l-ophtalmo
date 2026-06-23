import logging
import numpy as np
import hashlib
import json
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

SEGMENTATION_MODELS = ["optic_disc_cup", "vessel_seg", "lesion_seg"]
CLASSIFICATION_MODEL = "Kontawat/vit-diabetic-retinopathy-classification"


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
    return labels


def quantify_optic_disc_cup(label_path):
    """Compute cup/disc ratio from optic_disc_cup segmentation NRRD."""
    try:
        import nrrd
        data, header = nrrd.read(label_path)
        if data.ndim == 3:
            data = data[0] if data.shape[0] == 1 else data.squeeze()
        disc_pixels = int(np.sum(data == 1))
        cup_pixels = int(np.sum(data == 2))
        ratio = cup_pixels / disc_pixels if disc_pixels > 0 else 0.0
        return {
            "disc_area_px": disc_pixels,
            "cup_area_px": cup_pixels,
            "cup_disc_ratio": round(ratio, 4),
        }
    except Exception as e:
        logger.error(f"quantify_optic_disc_cup failed: {e}")
        return {"disc_area_px": 0, "cup_area_px": 0, "cup_disc_ratio": 0.0}


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
    """Count lesions from lesion segmentation NRRD and compute coverage."""
    try:
        import nrrd
        data, header = nrrd.read(label_path)
        if data.ndim == 3:
            data = data[0] if data.shape[0] == 1 else data.squeeze()
        total = int(data.size)

        ma = int(np.sum(data == 1))
        he = int(np.sum(data == 2))
        ex = int(np.sum(data == 3))
        any_lesion = int(np.sum(data > 0))
        coverage = (any_lesion / total * 100) if total > 0 else 0.0
        return {
            "microaneurysms": ma,
            "hemorrhages": he,
            "exudates": ex,
            "coverage_pct": round(coverage, 2),
        }
    except Exception as e:
        logger.error(f"quantify_lesions failed: {e}")
        return {"microaneurysms": 0, "hemorrhages": 0, "exudates": 0, "coverage_pct": 0.0}


def classify_dr(app, image_id):
    """Run DR classification model and return grade + confidence."""
    try:
        req = {
            "model": CLASSIFICATION_MODEL,
            "image": image_id,
            "result_extension": ".json",
            "restore_label_idx": False,
        }
        result = app.infer(req)
        if result and result.get("params"):
            params = result["params"]
            grade = params.get("label", params.get("prediction", "Unknown"))
            confidence = params.get("probability", params.get("confidence", 0.0))
            if isinstance(confidence, (list, np.ndarray)):
                confidence = float(max(confidence))
            return {"grade": str(grade), "confidence": round(float(confidence), 4)}
        logger.warning("DR classification returned no params")
    except Exception as e:
        logger.error(f"DR classification failed: {e}")
    return {"grade": "Unknown", "confidence": 0.0}


def build_report(optic, vessel, lesion, dr):
    """Assemble the complete analysis report."""
    return {
        "dr_classification": dr,
        "lesions": lesion,
        "optic_disc_cup": optic,
        "vessels": vessel,
    }


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

        text_lines = [
            "AI Ophthalmology Report",
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
