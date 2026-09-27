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

# Categorie/type minimaux exiges par le standard pour chaque segment.
_CATEGORY_TISSUE = ("T-D0050", "SRT", "Tissue")
_TYPE_TISSUE = ("T-D0050", "SRT", "Tissue")


def _code(value, scheme, meaning):
    ds = Dataset()
    ds.CodeValue = value
    ds.CodingSchemeDesignator = scheme
    ds.CodeMeaning = meaning
    return ds


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
    series_description=DOCTOR_SERIES_DESCRIPTION,
    series_number=9901,
    creator="Tele-Ophtalmo",
    creator_name=None,
):
    """Construit le Dataset DICOM-SEG.

    source_ds : Dataset de l'image OP corrigee (sert de reference spatiale).
    mask      : tableau 2D d'entiers, 0 = fond, n = index de segment.
    segments  : {index: libelle} pour les segments a ecrire.
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
    ds.SeriesDescription = series_description
    ds.InstanceNumber = 1
    ds.ContentLabel = "DOCTORCORR"
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

    now = getattr(source_ds, "StudyDate", "") or ""
    ds.SeriesDate = now
    ds.ContentDate = now
    ds.SeriesTime = getattr(source_ds, "StudyTime", "") or ""
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


def persist_doctor_correction(
    orthanc_url,
    sop_instance_uid,
    mask_payload,
    width,
    height,
    segments,
    creator_name=None,
):
    """Chaine complete : decodage, construction du SEG, envoi a Orthanc.

    Renvoie un dictionnaire decrivant la serie creee, a ranger dans le rapport
    pour que la correction reste retrouvable.
    """
    mask = decode_mask(mask_payload, width, height)
    source = fetch_source_dataset(orthanc_url, sop_instance_uid)
    ds = build_doctor_seg(source, mask, segments, creator_name=creator_name)
    instance_id = push_to_orthanc(orthanc_url, ds)
    return {
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
