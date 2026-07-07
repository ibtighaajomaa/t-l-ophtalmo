import logging
import os
from typing import Callable, Sequence

import numpy as np
import torch
from monai.data import MetaTensor
from monai.inferers import Inferer, SimpleInferer
from monai.transforms import (
    EnsureChannelFirstd,
    EnsureTyped,
    LoadImaged,
)

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask
from .optic_disc_cup import Ensure3ChannelRGBd, SqueezeDepthd

logger = logging.getLogger(__name__)

# Label encoding used by the published Xy.h5/test_Xy.h5 datasets.
LATERALITY_CLASSES = {0: "R", 1: "L"}


def preprocess_laterality_image(image, source_path="") -> np.ndarray:
    """Reproduce the preprocessing used to train the published model."""
    import cv2

    if isinstance(image, torch.Tensor):
        image = image.detach().cpu().numpy()

    image = np.asarray(image)
    if image.ndim == 4 and image.shape[0] == 1:
        image = image[0]
    if image.ndim != 3:
        raise ValueError(f"Expected a 3D CHW image, got shape {image.shape}")

    # MONAI supplies RGB/CHW while the original training pipeline used
    # cv2.imread (BGR/HWC).
    image = np.transpose(image, (1, 2, 0))
    if image.shape[-1] != 3:
        raise ValueError(f"Expected 3 color channels, got shape {image.shape}")
    if np.issubdtype(image.dtype, np.floating) and image.size and image.max() <= 1.0:
        image = image * 255.0
    image = np.clip(image, 0, 255).astype(np.uint8)
    image = image[..., ::-1]

    # MONAI's DICOM-to-NIfTI conversion rotates these OP images by 90 degrees.
    # Laterality depends on horizontal optic-disc position, so restore the
    # acquisition orientation for NIfTI sources.
    source_path = str(source_path or "").lower()
    if source_path.endswith((".nii", ".nii.gz")):
        image = np.rot90(image, k=1)
        logger.info("Restored fundus orientation after DICOM-to-NIfTI 90-degree rotation")

    foreground = np.any(image > 5, axis=2)
    rows, cols = np.where(foreground)
    if rows.size and cols.size:
        image = image[rows.min(): rows.max() + 1, cols.min(): cols.max() + 1]

    image = cv2.resize(image, (299, 299), interpolation=cv2.INTER_NEAREST)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    image = cv2.merge([clahe.apply(image[..., channel]) for channel in range(3)])

    mask = np.zeros((299, 299), dtype=np.uint8)
    cv2.circle(mask, (299 // 2, 299 // 2), int((299 // 2) * 0.95), 1, -1, 8, 0)
    image = np.where(mask[..., None].astype(bool), image, 128)

    return np.expand_dims(image.astype(np.float32) / 255.0, axis=0)


class EyeLaterality(BasicInferTask):
    def __init__(
        self,
        path,
        network=None,
        type=InferType.CLASSIFICATION,
        labels=None,
        dimension=2,
        description="InceptionV3-based eye laterality classification",
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
        self._keras_model = None

    def is_valid(self) -> bool:
        return True

    def pre_transforms(self, data=None) -> Sequence[Callable]:
        return [
            LoadImaged(keys="image"),
            EnsureTyped(keys="image", device=data.get("device") if data else None),
            EnsureChannelFirstd(keys="image"),
            Ensure3ChannelRGBd(keys="image"),
            SqueezeDepthd(keys="image"),
        ]

    def inferer(self, data=None) -> Inferer:
        return SimpleInferer()

    def run_inferer(self, data, convert_to_batch=True, device="cuda"):
        model = self._get_keras_model()
        image = data[self.input_key]
        source_path = data.get("image_path", "")
        if not source_path and hasattr(image, "meta"):
            source_path = image.meta.get("filename_or_obj", "")
        inputs = preprocess_laterality_image(image, source_path=source_path)

        predictions = model.predict(inputs, verbose=0)
        probs = np.asarray(predictions[0], dtype=np.float32)
        if probs.shape != (2,) or not np.all(np.isfinite(probs)):
            raise ValueError(f"Invalid eye laterality model output: {probs}")
        pred_class = int(np.argmax(probs))
        laterality = LATERALITY_CLASSES[pred_class]
        laterality_prob = float(probs[pred_class])

        logger.info("Eye Laterality: %s (confidence=%.4f)", laterality, laterality_prob)

        data[self.output_label_key] = MetaTensor(torch.from_numpy(probs))
        data[self.output_json_key] = {
            "laterality": laterality,
            "laterality_confidence": laterality_prob,
            "laterality_probabilities": {
                "R": float(probs[0]),
                "L": float(probs[1]),
            },
            "label_info": [
                {"name": "right", "color": [0, 0, 255]},
                {"name": "left", "color": [255, 0, 0]},
            ],
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
        if self._keras_model is not None:
            return self._keras_model

        from tensorflow import keras

        weight_path = self._find_weight_file()
        logger.info("Loading Keras InceptionV3 weights from: %s", weight_path)

        base = keras.applications.InceptionV3(
            include_top=False,
            weights=None,
            input_shape=(299, 299, 3),
        )
        x = keras.layers.GlobalAveragePooling2D()(base.output)
        x = keras.layers.Dense(1024, activation="relu")(x)
        outputs = keras.layers.Dense(2, activation="softmax")(x)
        model = keras.Model(inputs=base.input, outputs=outputs)

        if not weight_path:
            raise FileNotFoundError(
                "Eye laterality weights were not found; refusing to run an untrained model"
            )
        model.load_weights(weight_path)
        logger.info("Loaded pretrained weights from %s", weight_path)

        self._keras_model = model
        return model

    def _find_weight_file(self):
        if not self.path:
            return None
        paths = self.path if isinstance(self.path, (list, tuple)) else [self.path]
        for path in paths:
            if os.path.exists(path):
                return path
        return None
