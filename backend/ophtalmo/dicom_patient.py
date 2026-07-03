from datetime import date


def _parse_dicom_date(value):
    value = str(value or "").replace("-", "")
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def patient_metadata(orthanc_study):
    """Extract patient data from the DICOM tags returned by Orthanc."""
    patient_tags = orthanc_study.get("PatientMainDicomTags", {}) or {}
    study_tags = orthanc_study.get("MainDicomTags", {}) or {}

    def tag(name):
        return patient_tags.get(name) or study_tags.get(name) or ""

    birth_date = _parse_dicom_date(tag("PatientBirthDate"))
    age = None
    if birth_date:
        today = date.today()
        age = today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )

    history_parts = []
    for label, name in (
        ("Antécédents", "AdditionalPatientHistory"),
        ("Alertes médicales", "MedicalAlerts"),
        ("Allergies", "Allergies"),
        ("Commentaires", "PatientComments"),
    ):
        value = str(tag(name)).strip()
        if value:
            history_parts.append(f"{label} : {value}")

    return {
        "patient_id": str(tag("PatientID")).strip(),
        "patient_name": str(tag("PatientName") or "Unknown"),
        "patient_birth_date": birth_date,
        "patient_age": age,
        "patient_history": "\n".join(history_parts),
    }
