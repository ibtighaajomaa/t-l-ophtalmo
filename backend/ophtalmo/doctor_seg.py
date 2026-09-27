# -*- coding: utf-8 -*-
"""
Ecriture d'un DICOM-SEG a partir d'une correction de segmentation faite par
le medecin dans OHIF, et envoi vers Orthanc.

Pourquoi un vrai SEG et pas un masque interne : la correction devient une
serie du PACS, lisible par n'importe quelle visionneuse DICOM, auditable et
independante de cette application. Le rapport d'analyse dit qu'un medecin a
corrige la segmentation ; il faut que cette segmentation existe encore.

Point de vigilance : _delete_prior_ai_seg_series() dans tasks.py supprime les
series SEG dont la SeriesDescription figure dans AI_SEG_SERIES_DESCRIPTIONS
(les quatre noms de modeles). La description utilisee ici est volontairement
en dehors de cet ensemble, sinon une nouvelle analyse effacerait le travail
du medecin. Le test test_doctor_seg_survives_ai_cleanup verrouille ce point.
"""

import logging

import numpy as np
import requests
from pydicom import Dataset, Sequence
from pydicom.dataset import FileMetaDataset
from pydicom.uid import (
    ExplicitVRLittleEndian,
    UID,
    generate_uid,
)

logger = logging.getLogger(__name__)

# SOP Class "Segmentation Storage".
SEGMENTATION_STORAGE = UID("1.2.840.10008.5.1.4.1.1.66.4")

# Hors de AI_SEG_SERIES_DESCRIPTIONS : le nettoyage des SEG IA ne doit jamais
# faire disparaitre une correction de medecin.
# ASCII volontaire : sans SpecificCharacterSet, un accent dans un LO est un
# pari sur la visionneuse. Le sens reste clair dans la liste des series.
DOCTOR_SERIES_DESCRIPTION = "Corrige par medecin"

# Une seule version finale par photo ET par type de correction : sauvegarder
# les vaisseaux ne doit pas effacer la correction des lesions de la meme photo.
# Le type voyage dans ContentLabel (CS, 16 caracteres max) et dans le nom de
# serie, pour que le medecin distingue les corrections dans la liste.
DOCTOR_CONTENT_LABEL_PREFIX = "DRCORR_"
_KIND_CONTENT_LABEL = {
    "lesions": "LESIONS",
    "neovascularization": "NEOVASC",
    "vessels": "VESSELS",
    "optic_disc": "OPTICDISC",
    "unknown": "UNKNOWN",
}
_CONTENT_LABEL_KIND = {value: key for key, value in _KIND_CONTENT_LABEL.items()}
_KIND_DESCRIPTION_SUFFIX = {
    "lesions": "lesions",
    "neovascularization": "neovascularisation",
    "vessels": "vaisseaux",
    "optic_disc": "papille",
}

# Palette du viewer (getCommandsModule.ts, SEGMENT_CLASSES), cles normalisees.
# Sert de repli quand le viewer n'envoie pas la couleur d'un segment : sans
# RecommendedDisplayCIELabValue, OHIF affiche un avertissement et peint tout
# avec sa couleur par defaut.
_LABEL_RGB = {
    "microanevrismes": (255, 50, 50),
    "hemorragies": (59, 130, 246),
    "exsudats": (255, 255, 255),
    "nodules cotonneux": (0, 255, 0),
    "neovascularisation": (255, 200, 0),
    "disque optique": (0, 180, 130),
    "excavation papillaire": (255, 80, 160),
    "vaisseaux": (168, 85, 247),
    "drusen": (249, 115, 22),
    "cicatrices laser": (146, 64, 14),
}
_DEFAULT_RGB = (255, 50, 50)

# Categorie/type minimaux exiges par le standard pour chaque segment.
_CATEGORY_TISSUE = ("T-D0050", "SRT", "Tissue")
_TYPE_TISSUE = ("T-D0050", "SRT", "Tissue")


def _code(value, scheme, meaning):
    ds = Dataset()
    ds.CodeValue = value
    ds.CodingSchemeDesignator = scheme
    ds.CodeMeaning = meaning
    return ds


def normalize_kind(kind):
    kind = str(kind or "").strip().lower()
    return kind if kind in _KIND_CONTENT_LABEL else "unknown"


def doctor_series_description(kind):
    suffix = _KIND_DESCRIPTION_SUFFIX.get(normalize_kind(kind))
    return "%s - %s" % (DOCTOR_SERIES_DESCRIPTION, suffix) if suffix else DOCTOR_SERIES_DESCRIPTION


def doctor_content_label(kind):
    return DOCTOR_CONTENT_LABEL_PREFIX + _KIND_CONTENT_LABEL[normalize_kind(kind)]


def _normalize_label(label):
    import unicodedata

    text = unicodedata.normalize("NFD", str(label or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.lower().replace("_", " ").split())


def rgb_to_dicom_lab(rgb):
    """sRGB 8 bits -> CIELab (illuminant D65) code en DICOM.

    PS3.3 C.10.7.1.1 : L* 0..100 et a*, b* -128..127 sont mis a l'echelle sur
    0..65535. C'est l'inverse exact de dcmjs Colors.dicomlab2RGB, qu'OHIF
    utilise pour relire la couleur.
    """
    def linear(channel):
        c = max(0.0, min(1.0, float(channel) / 255.0))
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(v) for v in list(rgb)[:3])
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.00000
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t):
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x), f(y), f(z)
    lab_l = 116.0 * fy - 16.0
    lab_a = 500.0 * (fx - fy)
    lab_b = 200.0 * (fy - fz)

    def scale(value, low, high):
        return int(round(max(0.0, min(65535.0, (value - low) * 65535.0 / (high - low)))))

    return [scale(lab_l, 0.0, 100.0), scale(lab_a, -128.0, 127.0), scale(lab_b, -128.0, 127.0)]


def segment_rgb(index, label, segment_colors=None):
    """Couleur d'un segment : celle envoyee par le viewer, sinon la palette."""
    colors = segment_colors or {}
    raw = colors.get(index, colors.get(str(index)))
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return tuple(max(0, min(255, int(round(float(v))))) for v in raw[:3])
        except (TypeError, ValueError):
            pass
    return _LABEL_RGB.get(_normalize_label(label), _DEFAULT_RGB)


def _pack_frames(frames):
    """Empile les frames binaires et les emballe en bits, comme l'exige le
    standard : la concatenation est emballee d'un seul tenant, pas frame par
    frame."""
    if not frames:
        return b""
    flat = np.concatenate([np.asarray(f, dtype=np.uint8).ravel() for f in frames])
    packed = np.packbits(flat, bitorder="little")
    return packed.tobytes()


def build_doctor_seg(
    source_ds,
    mask,
    segments,
    series_description=None,
    series_number=9901,
    creator="Tele-Ophtalmo",
    creator_name=None,
    segment_colors=None,
    kind=None,
):
    """Construit le Dataset DICOM-SEG.

    source_ds : Dataset de l'image OP corrigee (sert de reference spatiale).
    mask      : tableau 2D d'entiers, 0 = fond, n = index de segment.
    segments  : {index: libelle} pour les segments a ecrire.
    segment_colors : {index: [r, g, b]} affichees dans le viewer (facultatif).
    kind      : type de correction (lesions, vessels, optic_disc...) ; il
                determine le nom de serie et le ContentLabel.
    """
    mask = np.asarray(mask)
    if mask.ndim != 2:
        raise ValueError("Le masque doit etre 2D (une image OP est monoframe).")

    rows, cols = mask.shape
    src_rows = int(getattr(source_ds, "Rows", rows) or rows)
    src_cols = int(getattr(source_ds, "Columns", cols) or cols)
    if (rows, cols) != (src_rows, src_cols):
        raise ValueError(
            "Dimensions du masque %sx%s incompatibles avec l'image source %sx%s"
            % (rows, cols, src_rows, src_cols)
        )

    # Un segment vide ne produit pas de frame : ecrire une frame vide ferait
    # croire a une structure presente mais nulle.
    present = [
        (index, label)
        for index, label in sorted(segments.items(), key=lambda kv: int(kv[0]))
        if np.any(mask == int(index))
    ]
    if not present:
        raise ValueError("Le masque ne contient aucun segment a enregistrer.")

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = SEGMENTATION_STORAGE
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SOPClassUID = SEGMENTATION_STORAGE
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "SEG"
    ds.SeriesInstanceUID = generate_uid()
    ds.SeriesNumber = series_number
    ds.SeriesDescription = series_description or doctor_series_description(kind)
    ds.InstanceNumber = 1
    ds.ContentLabel = doctor_content_label(kind)
    ds.ContentDescription = "Correction manuelle de segmentation"
    # ContentCreatorName est la personne (le medecin), Manufacturer le logiciel.
    ds.ContentCreatorName = creator_name or creator
    ds.Manufacturer = creator
    ds.DeviceSerialNumber = "0"
    ds.SoftwareVersions = "1.0"

    # Identite patient/etude reprise telle quelle : le SEG doit atterrir dans
    # la meme etude que l'image corrigee.
    for tag in (
        "PatientName", "PatientID", "PatientBirthDate", "PatientSex",
        "StudyInstanceUID", "StudyDate", "StudyTime", "StudyID",
        "AccessionNumber", "ReferringPhysicianName", "InstitutionName",
    ):
        if hasattr(source_ds, tag):
            setattr(ds, tag, getattr(source_ds, tag))
    ds.StudyInstanceUID = getattr(source_ds, "StudyInstanceUID", None) or generate_uid()

    # Date et heure de la CORRECTION, pas celles de l'examen : c'est ce qui
    # permet de dater chaque version dans le PACS et de garder la derniere.
    from datetime import datetime as _dt

    stamp = _dt.now()
    ds.SeriesDate = stamp.strftime("%Y%m%d")
    ds.ContentDate = ds.SeriesDate
    ds.SeriesTime = stamp.strftime("%H%M%S")
    ds.ContentTime = ds.SeriesTime

    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.BitsAllocated = 1
    ds.BitsStored = 1
    ds.HighBit = 0
    ds.SegmentationType = "BINARY"
    ds.LossyImageCompression = "00"
    ds.NumberOfFrames = len(present)

    # Description des segments.
    seg_seq = []
    for order, (index, label) in enumerate(present, start=1):
        item = Dataset()
        item.SegmentNumber = order
        item.SegmentLabel = str(label)
        item.SegmentAlgorithmType = "MANUAL"
        item.RecommendedDisplayCIELabValue = rgb_to_dicom_lab(
            segment_rgb(index, label, segment_colors)
        )
        item.SegmentedPropertyCategoryCodeSequence = Sequence([_code(*_CATEGORY_TISSUE)])
        item.SegmentedPropertyTypeCodeSequence = Sequence([_code(*_TYPE_TISSUE)])
        seg_seq.append(item)
    ds.SegmentSequence = Sequence(seg_seq)

    # Reference vers l'image source.
    ref_instance = Dataset()
    ref_instance.ReferencedSOPClassUID = getattr(source_ds, "SOPClassUID", "")
    ref_instance.ReferencedSOPInstanceUID = getattr(source_ds, "SOPInstanceUID", "")
    ref_series = Dataset()
    ref_series.SeriesInstanceUID = getattr(source_ds, "SeriesInstanceUID", "")
    ref_series.ReferencedInstanceSequence = Sequence([ref_instance])
    ds.ReferencedSeriesSequence = Sequence([ref_series])

    # Organisation dimensionnelle : une seule dimension, le numero de segment.
    dim_uid = generate_uid()
    dim_org = Dataset()
    dim_org.DimensionOrganizationUID = dim_uid
    ds.DimensionOrganizationSequence = Sequence([dim_org])
    dim_index = Dataset()
    dim_index.DimensionOrganizationUID = dim_uid
    dim_index.DimensionIndexPointer = 0x00620013  # ReferencedSegmentNumber
    dim_index.FunctionalGroupPointer = 0x00620012  # SegmentIdentificationSequence
    ds.DimensionIndexSequence = Sequence([dim_index])

    # Groupes fonctionnels partages : geometrie reprise de la source.
    pixel_measures = Dataset()
    pixel_measures.PixelSpacing = list(
        getattr(source_ds, "PixelSpacing", None) or [1.0, 1.0]
    )
    pixel_measures.SliceThickness = float(getattr(source_ds, "SliceThickness", 1.0) or 1.0)
    plane_orientation = Dataset()
    plane_orientation.ImageOrientationPatient = list(
        getattr(source_ds, "ImageOrientationPatient", None)
        or [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    )
    shared = Dataset()
    shared.PixelMeasuresSequence = Sequence([pixel_measures])
    shared.PlaneOrientationSequence = Sequence([plane_orientation])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])

    position = list(getattr(source_ds, "ImagePositionPatient", None) or [0.0, 0.0, 0.0])

    frames = []
    per_frame = []
    for order, (index, _label) in enumerate(present, start=1):
        frames.append((mask == int(index)).astype(np.uint8))

        frame = Dataset()
        plane_position = Dataset()
        plane_position.ImagePositionPatient = position
        frame.PlanePositionSequence = Sequence([plane_position])

        seg_id = Dataset()
        seg_id.ReferencedSegmentNumber = order
        frame.SegmentIdentificationSequence = Sequence([seg_id])

        content = Dataset()
        content.DimensionIndexValues = [order]
        frame.FrameContentSequence = Sequence([content])

        derivation_src = Dataset()
        derivation_src.ReferencedSOPClassUID = getattr(source_ds, "SOPClassUID", "")
        derivation_src.ReferencedSOPInstanceUID = getattr(source_ds, "SOPInstanceUID", "")
        derivation = Dataset()
        derivation.SourceImageSequence = Sequence([derivation_src])
        frame.DerivationImageSequence = Sequence([derivation])

        per_frame.append(frame)

    ds.PerFrameFunctionalGroupsSequence = Sequence(per_frame)
    ds.PixelData = _pack_frames(frames)

    return ds


def push_to_orthanc(orthanc_url, ds, timeout=30):
    """Envoie le SEG a Orthanc. Renvoie l'identifiant Orthanc de l'instance."""
    from io import BytesIO

    buffer = BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    payload = buffer.getvalue()

    response = requests.post(
        f"{orthanc_url.rstrip('/')}/instances",
        data=payload,
        headers={"Content-Type": "application/dicom"},
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    if isinstance(body, list):
        body = body[0] if body else {}
    instance_id = body.get("ID") or body.get("Id")
    logger.info(
        "[DoctorSeg] SEG envoye a Orthanc: instance=%s serie=%s",
        instance_id,
        ds.SeriesInstanceUID,
    )
    return instance_id


def decode_mask(payload, width, height):
    """Decode le masque envoye par le viewer.

    Deux formats acceptes, pour ne rien imposer au client :
      - 'rle'    : [valeur, longueur, valeur, longueur, ...] sur le tableau
                   aplati en row-major. Compact pour un masque creux et
                   trivial a produire depuis un Uint8Array.
      - 'base64' : PNG 8 bits en niveaux de gris, un niveau par index.
    """
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError("Dimensions de masque invalides.")

    kind = (payload or {}).get("encoding")
    if kind == "rle":
        runs = payload.get("data") or []
        if len(runs) % 2:
            raise ValueError("RLE malformee : nombre impair de valeurs.")
        flat = np.zeros(width * height, dtype=np.uint8)
        offset = 0
        for i in range(0, len(runs), 2):
            value, length = int(runs[i]), int(runs[i + 1])
            if length < 0 or offset + length > flat.size:
                raise ValueError("RLE malformee : longueur hors limites.")
            if value:
                flat[offset:offset + length] = value
            offset += length
        if offset != flat.size:
            raise ValueError(
                "RLE incomplete : %s pixels decrits pour %s attendus." % (offset, flat.size)
            )
        return flat.reshape(height, width)

    if kind == "base64":
        import base64
        from io import BytesIO

        from PIL import Image

        raw = base64.b64decode(payload.get("data") or "")
        image = Image.open(BytesIO(raw)).convert("L")
        if image.size != (width, height):
            raise ValueError(
                "PNG %sx%s incompatible avec %sx%s annonces"
                % (image.size[0], image.size[1], width, height)
            )
        return np.array(image, dtype=np.uint8)

    raise ValueError("Encodage de masque inconnu : %r" % (kind,))


def _lookup_instance(orthanc_url, sop_instance_uid, timeout=15):
    """Trouve l'identifiant Orthanc d'une instance a partir de son SOPInstanceUID."""
    response = requests.post(
        f"{orthanc_url.rstrip('/')}/tools/lookup",
        data=sop_instance_uid,
        timeout=timeout,
    )
    response.raise_for_status()
    for entry in response.json() or []:
        if entry.get("Type") == "Instance":
            return entry.get("ID")
    return None


def fetch_source_dataset(orthanc_url, sop_instance_uid, timeout=30):
    """Telecharge l'image OP corrigee depuis Orthanc."""
    from io import BytesIO

    from pydicom import dcmread

    instance_id = _lookup_instance(orthanc_url, sop_instance_uid, timeout=timeout)
    if not instance_id:
        raise LookupError(
            "Image source introuvable dans Orthanc : %s" % sop_instance_uid
        )
    response = requests.get(
        f"{orthanc_url.rstrip('/')}/instances/{instance_id}/file", timeout=timeout
    )
    response.raise_for_status()
    return dcmread(BytesIO(response.content))


def _seg_sources(tags):
    """SOPInstanceUID des images source citees par un SEG (tags simplifies)."""
    sources = set()
    for ref_series in tags.get("ReferencedSeriesSequence") or []:
        for ref in (ref_series or {}).get("ReferencedInstanceSequence") or []:
            if ref and ref.get("ReferencedSOPInstanceUID"):
                sources.add(ref["ReferencedSOPInstanceUID"])
    for frame in tags.get("PerFrameFunctionalGroupsSequence") or []:
        for derivation in (frame or {}).get("DerivationImageSequence") or []:
            for src in (derivation or {}).get("SourceImageSequence") or []:
                if src and src.get("ReferencedSOPInstanceUID"):
                    sources.add(src["ReferencedSOPInstanceUID"])
    return sources


def seg_kind_from_tags(tags):
    """Type d'une correction medecin deja stockee.

    Les series ecrites avant l'ajout du type portent ContentLabel DOCTORCORR :
    on deduit alors le type des libelles de segments, prudemment. Tout cas
    ambigu donne "unknown", qui ne correspond qu'a un autre "unknown".
    """
    label = str(tags.get("ContentLabel") or "").strip().upper()
    if label.startswith(DOCTOR_CONTENT_LABEL_PREFIX):
        return _CONTENT_LABEL_KIND.get(label[len(DOCTOR_CONTENT_LABEL_PREFIX):], "unknown")
    names = {_normalize_label(item.get("SegmentLabel")) for item in tags.get("SegmentSequence") or [] if item}
    names.discard("")
    if not names:
        return "unknown"
    if names <= {"vaisseaux"}:
        return "vessels"
    if names <= {"disque optique", "excavation papillaire"}:
        return "optic_disc"
    if names <= {"neovascularisation"}:
        return "neovascularization"
    lesion_names = {
        "microanevrismes", "hemorragies", "exsudats", "nodules cotonneux",
        "neovascularisation", "drusen", "cicatrices laser",
    }
    if names <= lesion_names:
        return "lesions"
    return "unknown"


def _is_doctor_series(series):
    description = str(((series or {}).get("MainDicomTags") or {}).get("SeriesDescription") or "")
    modality = str(((series or {}).get("MainDicomTags") or {}).get("Modality") or "")
    return modality == "SEG" and description.startswith(DOCTOR_SERIES_DESCRIPTION)


def list_doctor_segs(orthanc_url, study_instance_uid, timeout=20):
    """Toutes les corrections medecin d'une etude : [{orthanc_id, series_uid,
    sources, kind, last_update}]. N'inclut jamais une serie IA."""
    base = orthanc_url.rstrip("/")
    response = requests.post(base + "/tools/lookup", data=study_instance_uid, timeout=timeout)
    response.raise_for_status()
    study_ids = [e.get("ID") for e in response.json() or [] if e.get("Type") == "Study"]
    found = []
    for study_id in study_ids:
        series_list = requests.get(base + "/studies/%s/series" % study_id, timeout=timeout)
        series_list.raise_for_status()
        for series in series_list.json() or []:
            if not _is_doctor_series(series):
                continue
            instances = series.get("Instances") or []
            if not instances:
                continue
            tags = requests.get(base + "/instances/%s/tags?simplify" % instances[0], timeout=timeout)
            tags.raise_for_status()
            tags = tags.json() or {}
            found.append({
                "orthanc_id": series.get("ID"),
                "series_uid": (series.get("MainDicomTags") or {}).get("SeriesInstanceUID"),
                "sources": _seg_sources(tags),
                "kind": seg_kind_from_tags(tags),
                "last_update": series.get("LastUpdate") or "",
            })
    return found


def delete_prior_doctor_segs(orthanc_url, study_instance_uid, source_sop_instance_uid, kind,
                             keep_series_uid, timeout=20):
    """Supprime les versions precedentes : memes photo source ET meme type.

    Appelee APRES l'envoi reussi de la nouvelle version, jamais avant : un
    echec d'enregistrement ne doit pas faire perdre la precedente.
    """
    kind = normalize_kind(kind)
    deleted = []
    for seg in list_doctor_segs(orthanc_url, study_instance_uid, timeout=timeout):
        if seg["series_uid"] == keep_series_uid:
            continue
        if source_sop_instance_uid not in seg["sources"] or seg["kind"] != kind:
            continue
        response = requests.delete(
            "%s/series/%s" % (orthanc_url.rstrip("/"), seg["orthanc_id"]), timeout=timeout
        )
        response.raise_for_status()
        deleted.append(seg["series_uid"])
        logger.info("[DoctorSeg] version precedente supprimee : serie=%s type=%s", seg["series_uid"], kind)
    return deleted


def persist_doctor_correction(
    orthanc_url,
    sop_instance_uid,
    mask_payload,
    width,
    height,
    segments,
    creator_name=None,
    segment_colors=None,
    kind=None,
):
    """Chaine complete : decodage, construction du SEG, envoi a Orthanc, puis
    suppression de la version precedente de la meme photo et du meme type.

    Renvoie un dictionnaire decrivant la serie creee, a ranger dans le rapport
    pour que la correction reste retrouvable.
    """
    mask = decode_mask(mask_payload, width, height)
    source = fetch_source_dataset(orthanc_url, sop_instance_uid)
    ds = build_doctor_seg(
        source, mask, segments, creator_name=creator_name,
        segment_colors=segment_colors, kind=kind,
    )
    instance_id = push_to_orthanc(orthanc_url, ds)

    # La nouvelle version est dans le PACS : on peut retirer l'ancienne. Un
    # echec ici n'annule pas l'enregistrement, il laisse seulement un doublon.
    replaced = []
    replace_error = None
    try:
        replaced = delete_prior_doctor_segs(
            orthanc_url, str(ds.StudyInstanceUID), str(sop_instance_uid), kind,
            keep_series_uid=str(ds.SeriesInstanceUID),
        )
    except Exception as exc:  # doublon tolere, jamais de perte
        logger.exception("[DoctorSeg] suppression de la version precedente impossible")
        replace_error = str(exc)
    return {
        "kind": normalize_kind(kind),
        "replaced_series_uids": replaced,
        "replace_error": replace_error,
        "orthanc_instance_id": instance_id,
        "seg_series_instance_uid": str(ds.SeriesInstanceUID),
        "seg_sop_instance_uid": str(ds.SOPInstanceUID),
        "series_description": str(ds.SeriesDescription),
        "content_creator_name": str(ds.ContentCreatorName),
        "source_sop_instance_uid": str(sop_instance_uid),
        "segment_labels": {
            int(item.SegmentNumber): str(item.SegmentLabel) for item in ds.SegmentSequence
        },
    }
