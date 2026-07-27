import logging
from typing import Callable, Sequence

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from monai.data import MetaTensor
from monai.transforms import (
    EnsureChannelFirstd,
    EnsureTyped,
    LoadImaged,
    MapTransform,
    Resized,
    ScaleIntensityRanged,
)

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask
from .optic_disc_cup import Ensure3ChannelRGBd, SqueezeDepthd
from transformers import AutoImageProcessor, SegformerForSemanticSegmentation

logger = logging.getLogger(__name__)

ODOC_MODEL_ID = "pamixsun/segformer_for_optic_disc_cup_segmentation"


def suppress_optic_disc_lesions(prediction, odoc_prediction, margin_ratio=0.015):
    """Remove lesion labels on and immediately around the optic disc/cup."""
    lesions = np.asarray(prediction).copy()
    odoc = np.asarray(odoc_prediction)
    if lesions.ndim != 2 or odoc.ndim != 2:
        raise ValueError("Lesion and optic-disc predictions must both be 2D")
    if odoc.shape != lesions.shape:
        odoc = cv2.resize(
            odoc.astype(np.uint8),
            (lesions.shape[1], lesions.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )

    exclusion = (odoc > 0).astype(np.uint8)
    if not exclusion.any():
        return lesions

    margin = max(1, int(round(min(lesions.shape) * margin_ratio)))
    kernel_size = margin * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    exclusion = cv2.dilate(exclusion, kernel, iterations=1).astype(bool)
    removed = int(np.count_nonzero(lesions[exclusion]))
    lesions[exclusion] = 0
    logger.info("Suppressed %s lesion pixels overlapping the optic disc/cup", removed)
    return lesions


def suppress_macular_zone_lesions(prediction, radius_ratio=0.08):
    """Remove complete lesion components that intersect the macular zone."""
    lesions = np.asarray(prediction).copy()
    if lesions.ndim != 2:
        raise ValueError("Lesion prediction must be 2D")

    height, width = lesions.shape
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    radius = max(1.0, min(height, width) * float(radius_ratio))
    yy, xx = np.ogrid[:height, :width]
    macular_zone = (xx - center_x) ** 2 + (yy - center_y) ** 2 <= radius ** 2
    removed = 0
    removed_components = 0
    for class_id in np.unique(lesions):
        if class_id == 0:
            continue
        count, components = cv2.connectedComponents(
            (lesions == class_id).astype(np.uint8), connectivity=8
        )
        for component_id in range(1, count):
            component = components == component_id
            if np.any(component & macular_zone):
                removed += int(np.count_nonzero(component))
                removed_components += 1
                lesions[component] = 0
    logger.info(
        "Suppressed %s macular lesion components (%s pixels)",
        removed_components,
        removed,
    )
    return lesions


class CaptureOriginalSpatialShaped(MapTransform):
    """Retain the source OP dimensions before resizing for DeepLabV3+."""

    def __call__(self, data):
        result = dict(data)
        image = result[self.keys[0]]
        result["lesion_original_shape"] = tuple(int(v) for v in image.shape[-2:])
        return result


class LesionSeg(BasicInferTask):
    def __init__(
        self,
        path,
        network=None,
        type=InferType.SEGMENTATION,
        labels=None,
        dimension=2,
        description="DDR DeepLabV3+ EfficientNet-B3 retinal lesion segmentation",
        **kwargs,
    ):
        super().__init__(
            path=path,
            network=network,
            type=type,
            labels=labels,
            dimension=dimension,
            description=description,
            load_strict=False,
            **kwargs,
        )
        self._odoc_model = None
        self._odoc_processor = None

    def _load_odoc_model(self, device):
        if self._odoc_model is None:
            logger.info("Loading optic-disc model for lesion false-positive suppression")
            self._odoc_processor = AutoImageProcessor.from_pretrained(ODOC_MODEL_ID)
            self._odoc_model = SegformerForSemanticSegmentation.from_pretrained(ODOC_MODEL_ID)
            self._odoc_model.eval()
        self._odoc_model.to(device)
        return self._odoc_model

    def _predict_optic_disc(self, image, device):
        array = image.detach().float().cpu().numpy() if torch.is_tensor(image) else np.asarray(image)
        array = np.transpose(array[:3], (1, 2, 0))
        if array.size and float(array.max()) <= 1.0:
            array = array * 255.0
        array = np.clip(array, 0, 255).astype(np.uint8)
        model = self._load_odoc_model(device)
        inputs = self._odoc_processor(images=array, return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.no_grad():
            logits = model(**inputs).logits
        logits = F.interpolate(
            logits, size=image.shape[-2:], mode="bilinear", align_corners=False
        )
        return logits.argmax(dim=1)[0].cpu().numpy().astype(np.uint8)

    def is_valid(self) -> bool:
        # Missing or invalid checkpoints are reported explicitly during load.
        return True

    def pre_transforms(self, data=None) -> Sequence[Callable]:
        return [
            LoadImaged(keys="image"),
            EnsureTyped(keys="image", device=data.get("device") if data else None),
            EnsureChannelFirstd(keys="image"),
            Ensure3ChannelRGBd(keys="image"),
            SqueezeDepthd(keys="image"),
            CaptureOriginalSpatialShaped(keys="image"),
            Resized(keys="image", spatial_size=(512, 512), mode="bilinear"),
            ScaleIntensityRanged(
                keys="image",
                a_min=0,
                a_max=255,
                b_min=0.0,
                b_max=1.0,
                clip=True,
            ),
        ]

    def run_inferer(self, data, convert_to_batch=True, device="cuda"):
        image = data[self.input_key]
        original_shape = tuple(data.get("lesion_original_shape") or image.shape[-2:])
        network = self._get_network(device, data)
        inputs = image if torch.is_tensor(image) else torch.as_tensor(image)
        inputs = inputs.unsqueeze(0) if convert_to_batch else inputs
        with torch.no_grad():
            logits = network(inputs.to(torch.device(device)))
            prediction = torch.softmax(logits, dim=1).argmax(dim=1)[0].cpu().numpy().astype(np.uint8)
        odoc_prediction = self._predict_optic_disc(image, torch.device(device))
        prediction = suppress_optic_disc_lesions(prediction, odoc_prediction)
        prediction = suppress_macular_zone_lesions(prediction)
        if prediction.shape != original_shape:
            prediction = cv2.resize(
                prediction,
                (original_shape[1], original_shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        meta = dict(getattr(image, "meta", {}) or {})
        data[self.output_label_key] = MetaTensor(
            torch.from_numpy(prediction.astype(np.uint8)), meta=meta
        )
        data[self.output_json_key] = {
            "label_info": [
                {"label": 1, "name": "Microanevrismes", "color": [255, 50, 50]},
                {"label": 2, "name": "Hemorragies", "color": [50, 50, 255]},
                {"label": 3, "name": "Exsudats solides", "color": [160, 160, 160]},
                {"label": 4, "name": "Exsudats cotonneux", "color": [0, 255, 0]},
            ],
            "model_id": "DDR-DeepLabV3Plus-EfficientNetB3",
            "dataset": "DDR",
            "preprocessing": "512x512 RGB, intensity scaled to [0,1]",
        }
        return data

    def run_invert_transforms(self, data, pre_transforms, transforms):
        return data

    def post_transforms(self, data=None) -> Sequence[Callable]:
        return []

    def writer(self, data, extension=None, dtype=None):
        result_file, result_json = super().writer(data, extension, dtype)
        if self.output_json_key in data and isinstance(data[self.output_json_key], dict):
            result_json.update(data[self.output_json_key])
        return result_file, result_json
