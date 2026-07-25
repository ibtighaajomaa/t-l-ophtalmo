import hashlib
import logging
import os
from typing import Callable, Sequence

import cv2
import numpy as np
import tensorflow as tf
import torch
from monai.data import MetaTensor
from monai.transforms import EnsureChannelFirstd, EnsureTyped, LoadImaged
from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask

from .optic_disc_cup import Ensure3ChannelRGBd, SqueezeDepthd

logger = logging.getLogger(__name__)

CHECKPOINT_SHA256 = "f4c3c89a4da02b84af6cc85b4ee9cd4be35bf2c836cf230b0a6d06a3805b646b"
NEOVASCULARIZATION_CLASS = 5


class NeovascularizationSeg(BasicInferTask):
    def __init__(
        self,
        path,
        labels=None,
        type=InferType.SEGMENTATION,
        dimension=2,
        description="BigEye DeepLabV3+ neovascularization segmentation",
        **kwargs,
    ):
        super().__init__(
            path=path,
            network=None,
            type=type,
            labels=labels,
            dimension=dimension,
            description=description,
            **kwargs,
        )
        self._keras_model = None

    def _model_path(self):
        paths = self.path if isinstance(self.path, (list, tuple)) else [self.path]
        return next((path for path in reversed(paths) if path and os.path.isfile(path)), None)

    def is_valid(self) -> bool:
        return self._model_path() is not None

    def pre_transforms(self, data=None) -> Sequence[Callable]:
        return [
            LoadImaged(keys="image"),
            EnsureTyped(keys="image", device="cpu"),
            EnsureChannelFirstd(keys="image"),
            Ensure3ChannelRGBd(keys="image"),
            SqueezeDepthd(keys="image"),
        ]

    def _get_model(self):
        if self._keras_model is None:
            model_path = self._model_path()
            if model_path is None:
                raise FileNotFoundError(f"BigEye checkpoint not found: {self.path}")
            digest = hashlib.sha256()
            with open(model_path, "rb") as model_file:
                for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != CHECKPOINT_SHA256:
                raise RuntimeError("BigEye checkpoint SHA-256 mismatch")
            logger.info("Loading official BigEye model from %s", model_path)
            self._keras_model = tf.keras.models.load_model(model_path, compile=False)
        return self._keras_model

    @staticmethod
    def _preprocess(image_chw: np.ndarray) -> np.ndarray:
        rgb = np.transpose(image_chw, (1, 2, 0))
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        resized = cv2.resize(bgr, (512, 512), interpolation=cv2.INTER_AREA)
        lab = cv2.cvtColor(resized, cv2.COLOR_BGR2LAB)
        lightness, channel_a, channel_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = cv2.cvtColor(
            cv2.merge((clahe.apply(lightness), channel_a, channel_b)),
            cv2.COLOR_LAB2BGR,
        )
        return enhanced.astype(np.float32) / 255.0

    def run_inferer(self, data, convert_to_batch=True, device="cpu"):
        image = data[self.input_key]
        image_np = image.detach().cpu().numpy() if torch.is_tensor(image) else np.asarray(image)
        original_shape = tuple(int(value) for value in image_np.shape[-2:])
        inputs = self._preprocess(image_np)[None, ...]
        probabilities = self._get_model().predict(inputs, verbose=0)
        all_classes = np.argmax(probabilities, axis=-1)[0]
        class_pixel_counts = {
            str(class_id): int(np.sum(all_classes == class_id))
            for class_id in range(int(probabilities.shape[-1]))
        }
        neovascularization = (all_classes == NEOVASCULARIZATION_CLASS).astype(np.uint8)
        neovascularization = cv2.resize(
            neovascularization,
            (original_shape[1], original_shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
        meta = dict(getattr(image, "meta", {}) or {})
        data[self.output_label_key] = MetaTensor(torch.from_numpy(neovascularization), meta=meta)
        data[self.output_json_key] = {
            "label_info": [
                {"label": 1, "name": "Neovascularisation", "color": [255, 215, 0]},
            ],
            "model_id": "hmgill/BigEye",
            "model_task": "class_5_neovascularization",
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "preprocessing": "512x512 BGR, CLAHE LAB L-channel, scaled to [0,1]",
            "neovascularization_pixels": int(np.sum(neovascularization)),
            "class_pixel_counts_512": class_pixel_counts,
        }
        logger.info(
            "BigEye class pixels at 512x512: %s; neovascularization at source resolution: %d",
            class_pixel_counts,
            int(np.sum(neovascularization)),
        )
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
