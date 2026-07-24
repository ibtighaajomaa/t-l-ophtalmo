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
)

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask
from .optic_disc_cup import Ensure3ChannelRGBd, SqueezeDepthd
from .bigeye import LESION_COLORS, LESION_NAMES, load_bigeye_model, model_metadata, predict_bigeye

logger = logging.getLogger(__name__)


class LesionSeg(BasicInferTask):
    def __init__(
        self,
        path,
        network=None,
        type=InferType.SEGMENTATION,
        labels=None,
        dimension=2,
        description="BigEye DeepLab retinal lesion segmentation (six lesion classes)",
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
        # Load eagerly so a missing, corrupt, or incompatible checkpoint keeps
        # the service unhealthy instead of producing a partial lesion report.
        self._keras_model = load_bigeye_model(self.path)

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
        ]

    def run_inferer(self, data, convert_to_batch=True, device="cuda"):
        image = data[self.input_key]
        original_shape = tuple(image.shape[-2:])
        prediction = predict_bigeye(self._get_keras_model(), image)
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
                {"name": LESION_NAMES[class_id], "color": list(LESION_COLORS[class_id])}
                for class_id in range(1, 7)
            ],
            **model_metadata(),
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

    def _get_keras_model(self):
        if self._keras_model is None:
            self._keras_model = load_bigeye_model(self.path)
        return self._keras_model
