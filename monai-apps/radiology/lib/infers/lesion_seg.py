import logging
from typing import Callable, Sequence

import cv2
import numpy as np
import torch
from monai.data import MetaTensor
from monai.transforms import (
    EnsureChannelFirstd,
    EnsureTyped,
    LoadImaged,
    Resized,
    ScaleIntensityRanged,
)

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask
from .optic_disc_cup import Ensure3ChannelRGBd, SqueezeDepthd

logger = logging.getLogger(__name__)


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
            Resized(keys="image", spatial_size=(512, 512), mode="bilinear"),
            ScaleIntensityRanged(keys="image", a_min=0, a_max=255, b_min=0.0, b_max=1.0, clip=True),
        ]

    def run_inferer(self, data, convert_to_batch=True, device="cuda"):
        image = data[self.input_key]
        original_shape = tuple(image.shape[-2:])
        network = self._get_network(device, data)
        inputs = image if torch.is_tensor(image) else torch.as_tensor(image)
        inputs = inputs.unsqueeze(0) if convert_to_batch else inputs
        with torch.no_grad():
            logits = network(inputs.to(torch.device(device)))
            prediction = torch.softmax(logits, dim=1).argmax(dim=1)[0].cpu().numpy().astype(np.uint8)
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
                {"name": "microaneurysms", "color": [255, 50, 50]},
                {"name": "hemorrhages", "color": [50, 50, 255]},
                {"name": "hard_exudates", "color": [160, 160, 160]},
                {"name": "soft_exudates", "color": [0, 255, 0]},
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
