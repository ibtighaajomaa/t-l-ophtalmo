import requests

UNKNOWN_INSTITUTION = "Établissement inconnu"

MODALITY_SITES = {
    ("192.168.167.116", "Canon RC Capture"): "kelibia",
    ("192.168.167.117", "RETINO_KELIBIA"): "Hôpital de Kélibia",
}

MODALITY_IP_SITES = {
    "192.168.149.10": "Manzel Temim",
    "192.168.167.116": "kelibia",
    "172.22.12.232": "kebili",
    "192.168.149.6": "Manzel Temim",
    "192.168.254.44": "Deguech",
    "172.22.158.100": "Mateur",
    "192.172.35.37": "Siliana",
}

MODALITY_AET_SITES = {
    "Canon RC Capture": "kelibia",
    "RETINO_KELIBIA": "Hôpital de Kélibia",
}


def _lookup_site(remote_ip, remote_aet):
    try:
        from .models import DicomModalitySite
    except Exception:
        return ""

    if remote_ip and remote_aet:
        site = (
            DicomModalitySite.objects.filter(
                remote_ip=remote_ip,
                remote_aet=remote_aet,
                is_active=True,
            )
            .values_list("institution_name", flat=True)
            .first()
        )
        if site:
            return site

    if remote_ip:
        site = (
            DicomModalitySite.objects.filter(
                remote_ip=remote_ip,
                is_active=True,
            )
            .exclude(remote_ip="")
            .values_list("institution_name", flat=True)
            .first()
        )
        if site:
            return site

    if remote_aet:
        site = (
            DicomModalitySite.objects.filter(
                remote_aet=remote_aet,
                is_active=True,
            )
            .exclude(remote_aet="")
            .values_list("institution_name", flat=True)
            .first()
        )
        if site:
            return site

    return ""


def lookup_site_name(remote_ip="", remote_aet=""):
    return _lookup_site(remote_ip or "", remote_aet or "")


def _metadata_value(orthanc_url, instance_id, key, http=requests):
    try:
        response = http.get(
            f"{orthanc_url}/instances/{instance_id}/metadata/{key}",
            timeout=5,
        )
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        text = response.text if isinstance(response.text, str) else ""
        return text.strip().strip('"')
    except requests.RequestException:
        return ""


def _first_op_instance_id(orthanc_url, study_meta, http=requests):
    for series_id in (study_meta.get("Series") or []):
        try:
            response = http.get(f"{orthanc_url}/series/{series_id}", timeout=5)
            response.raise_for_status()
            series = response.json()
        except requests.RequestException:
            continue

        modality = (series.get("MainDicomTags") or {}).get("Modality")
        if modality != "OP":
            continue

        instances = series.get("Instances") or []
        if instances:
            return instances[0]
    return ""


def _institution_from_dicom(study_meta):
    main_tags = study_meta.get("MainDicomTags") or {}
    institution = (main_tags.get("InstitutionName") or "").strip()
    if institution:
        return institution

    patient_tags = study_meta.get("PatientMainDicomTags") or {}
    return (patient_tags.get("InstitutionName") or "").strip()


def resolve_study_origin(orthanc_url, study_meta, http=requests):
    """
    Resolve where a DICOM study came from.

    Priority:
    1. IP + AET mapping.
    2. RemoteIP mapping.
    3. RemoteAET mapping.
    4. DICOM InstitutionName when no mapping exists.
    5. Unknown institution fallback.
    """
    institution = _institution_from_dicom(study_meta)
    instance_id = _first_op_instance_id(orthanc_url, study_meta, http=http)

    remote_ip = ""
    remote_aet = ""
    called_aet = ""
    origin = ""
    if instance_id:
        remote_ip = _metadata_value(orthanc_url, instance_id, "RemoteIP", http=http)
        remote_aet = _metadata_value(orthanc_url, instance_id, "RemoteAET", http=http)
        called_aet = _metadata_value(orthanc_url, instance_id, "CalledAET", http=http)
        origin = _metadata_value(orthanc_url, instance_id, "Origin", http=http)

    region = (
        _lookup_site(remote_ip, remote_aet)
        or MODALITY_SITES.get((remote_ip, remote_aet))
        or MODALITY_IP_SITES.get(remote_ip)
        or MODALITY_AET_SITES.get(remote_aet)
        or institution
        or UNKNOWN_INSTITUTION
    )

    return {
        "region": region,
        "modality_ip": remote_ip,
        "remote_aet": remote_aet,
        "called_aet": called_aet,
        "origin": origin,
        "orthanc_instance_id": instance_id,
    }
