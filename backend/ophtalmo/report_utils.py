import os
import requests


def build_ai_report_text(patient_id, report_data, eye, patient_age=None):
    url = os.environ.get("REPORT_GENERATOR_URL", "http://report-generator:8010")
    payload = {
        "patient_id": patient_id or "inconnu",
        "report_data": report_data,
    }
    resp = requests.post(f"{url}/report", json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json().get("report", {})
    return {
        "report_text": result.get("report_text", ""),
        "report_html": result.get("report_html", ""),
        "report_json": result.get("report_json", {"report_engine": "local-formatter"}),
    }
