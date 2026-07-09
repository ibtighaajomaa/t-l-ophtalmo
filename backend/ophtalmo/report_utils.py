import os
import json
import requests


def _find_orthanc_series_id(orthanc_url, series_uid):
    if not series_uid:
        return None
    resp = requests.post(
        f"{orthanc_url}/tools/find",
        json={"Level": "Series", "Query": {"SeriesInstanceUID": series_uid}},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    return results[0] if results else None


def _fetch_rendered_series_image(orthanc_url, series_uid):
    orthanc_series_id = _find_orthanc_series_id(orthanc_url, series_uid)
    if not orthanc_series_id:
        return None

    series_detail = requests.get(
        f"{orthanc_url}/series/{orthanc_series_id}",
        timeout=10,
    )
    series_detail.raise_for_status()
    instances = series_detail.json().get("Instances") or []
    if not instances:
        return None

    image_resp = requests.get(
        f"{orthanc_url}/instances/{instances[0]}/rendered",
        timeout=30,
    )
    image_resp.raise_for_status()
    return {
        "content": image_resp.content,
        "content_type": image_resp.headers.get("Content-Type", "image/png"),
    }


def _normalize_source_series_uid(report_data):
    candidate = (
        (report_data or {}).get("source_series_uid")
        or next(iter((report_data or {}).get("series_instance_uids") or []), "")
    )
    if not candidate:
        source = (report_data or {}).get("source") or {}
        candidate = source.get("series_instance_uid", "")
    return str(candidate).split(":", 1)[0] if candidate else ""


def build_ai_report_text(patient_id, report_data, eye, patient_age=None, series_uid=None):
    url = os.environ.get("REPORT_GENERATOR_URL", "http://report-generator:8010")
    orthanc_url = os.environ.get("ORTHANC_URL", "http://orthanc-container:8042")
    series_uid = series_uid or _normalize_source_series_uid(report_data)

    if series_uid:
        try:
            rendered = _fetch_rendered_series_image(orthanc_url, series_uid)
            if rendered:
                form_data = {
                    "patient_id": patient_id or "inconnu",
                    "eye": eye or "Non spécifié",
                    "monai_data": json.dumps(report_data or {}),
                }
                if patient_age not in (None, ""):
                    form_data["patient_age"] = patient_age
                resp = requests.post(
                    f"{url}/generate",
                    files={
                        "file": (
                            "fundus.png",
                            rendered["content"],
                            rendered["content_type"],
                        )
                    },
                    data=form_data,
                    timeout=600,
                )
                resp.raise_for_status()
                result = resp.json()
                return {
                    "report_text": result.get("report_text", ""),
                    "report_html": result.get("report_html", ""),
                    "report_json": result.get(
                        "report_json",
                        {"report_engine": "medgemma-1.5-4b-it", "used_image": True},
                    ),
                }
        except Exception:
            pass

    payload = {
        "patient_id": patient_id or "inconnu",
        "patient_age": patient_age,
        "eye": eye or "Non spécifié",
        "report_data": report_data,
    }
    resp = requests.post(f"{url}/report", json=payload, timeout=600)
    resp.raise_for_status()
    result = resp.json().get("report", {})
    return {
        "report_text": result.get("report_text", ""),
        "report_html": result.get("report_html", ""),
        "report_json": result.get("report_json", {"report_engine": "medgemma-1.5-4b-it"}),
    }
