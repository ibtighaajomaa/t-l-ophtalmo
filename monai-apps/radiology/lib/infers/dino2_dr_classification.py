import hashlib
import os
from pathlib import Path
from typing import Callable, Sequence

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from monai.data import MetaTensor
from monai.inferers import Inferer, SimpleInferer
from monai.transforms import LoadImaged, MapTransform

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask

DINO2_DR_CLASSES = {
    0: "No DR",
    1: "Mild NPDR",
    2: "Moderate NPDR",
    3: "Severe NPDR",
    4: "Proliferative DR",
}
IMAGENET_MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)[:, None, None]
IMAGENET_STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)[:, None, None]
OFFICIAL_COMMIT = "c8e3b3f88499dbad1a5f39a87d0cb20505cbedd6"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preprocess_dino2_dr(image):
    array = np.asarray(image)
    array = np.squeeze(array)
    # MONAI can expose a multi-frame OP series as H×W×N×C. Dino2-DR
    # classifies one fundus photograph at a time, matching the endpoint's
    # single-instance contract.
    if array.ndim > 3 and array.shape[-1] in (1, 3, 4):
        array = array.reshape(array.shape[0], array.shape[1], -1, array.shape[-1])[:, :, 0, :]
    if array.ndim == 3 and array.shape[0] in (1, 3, 4):
        array = np.moveaxis(array, 0, -1)
    if array.ndim == 2:
        gray = array.astype(np.uint8)
    else:
        rgb = array[..., :3].astype(np.uint8)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    blurred = cv2.GaussianBlur(gray, (15, 15), 0)
    _, mask = cv2.threshold(blurred, 30, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("Dino2-DR fundus field not detected")
    contour = max(contours, key=cv2.contourArea)
    hull = cv2.convexHull(contour)
    fundus_mask = np.zeros_like(gray)
    cv2.drawContours(fundus_mask, [hull], -1, 255, -1)
    x, y, width, height = cv2.boundingRect(hull)

    processed = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    processed = cv2.GaussianBlur(processed, (5, 5), 0)
    processed = cv2.medianBlur(processed, 5)
    processed = cv2.bitwise_and(processed, processed, mask=fundus_mask)
    cropped = processed[y : y + height, x : x + width]

    target = int(512 * 0.9)
    scale = target / max(cropped.shape)
    resized = cv2.resize(
        cropped,
        (max(1, round(cropped.shape[1] * scale)), max(1, round(cropped.shape[0] * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    canvas = np.zeros((512, 512), dtype=np.uint8)
    top = (512 - resized.shape[0]) // 2
    left = (512 - resized.shape[1]) // 2
    canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
    canvas = cv2.resize(canvas, (504, 504), interpolation=cv2.INTER_AREA)
    tensor = np.repeat(canvas[None, ...], 3, axis=0).astype(np.float32) / 255.0
    return torch.from_numpy((tensor - IMAGENET_MEAN) / IMAGENET_STD)


class Dino2DRPreprocessd(MapTransform):
    def __call__(self, data):
        output = dict(data)
        output[self.keys[0]] = MetaTensor(preprocess_dino2_dr(output[self.keys[0]]))
        return output


class Dino2DRModel(nn.Module):
    def __init__(self, backbone):
        super().__init__()
        self.backbone = backbone
        self.classifier = nn.Sequential(
            nn.Linear(1536, 512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, 5),
        )

    def forward(self, inputs):
        features = self.backbone(inputs)
        if isinstance(features, dict):
            features = features["x_norm_clstoken"]
        elif isinstance(features, tuple):
            features = features[0]
        return self.classifier(features)


class Dino2DRClassification(BasicInferTask):
    def __init__(self, path, network=None, type=InferType.CLASSIFICATION, labels=None, dimension=2, **kwargs):
        super().__init__(
            path=path,
            network=network,
            type=type,
            labels=labels,
            dimension=dimension,
            description="Dino2-DR FSMT comparative diabetic retinopathy classification",
            load_strict=True,
            **kwargs,
        )
        self.checkpoint_path = os.environ.get(
            "DINO2_DR_CHECKPOINT_PATH", "/opt/monai/models/dino2-dr/dino2_dr_fsmt.pth"
        )
        self.expected_sha256 = os.environ.get("DINO2_DR_CHECKPOINT_SHA256", "").strip().lower()
        self._model = None

    def is_valid(self):
        return True

    def pre_transforms(self, data=None) -> Sequence[Callable]:
        return [LoadImaged(keys="image"), Dino2DRPreprocessd(keys="image")]

    def inferer(self, data=None) -> Inferer:
        return SimpleInferer()

    def _load_model(self):
        if self._model is not None:
            return self._model
        checkpoint = Path(self.checkpoint_path)
        if not checkpoint.is_file():
            raise FileNotFoundError("checkpoint spécialisé Dino2-DR FSMT officiel non installé")
        if not self.expected_sha256:
            raise RuntimeError("DINO2_DR_CHECKPOINT_SHA256 is required")
        actual_sha256 = sha256_file(checkpoint)
        if actual_sha256 != self.expected_sha256:
            raise RuntimeError("Dino2-DR checkpoint SHA-256 mismatch")
        backbone = torch.hub.load("facebookresearch/dinov2", "dinov2_vitg14_reg")
        model = Dino2DRModel(backbone)
        checkpoint_data = torch.load(checkpoint, map_location="cpu", weights_only=True)
        state_dict = checkpoint_data.get("model_state_dict", checkpoint_data)
        model.load_state_dict(state_dict, strict=True)
        model.eval()
        self._model = model
        return model

    def run_inferer(self, data, convert_to_batch=True, device="cpu"):
        inputs = data[self.input_key]
        inputs = inputs.unsqueeze(0) if convert_to_batch else inputs
        with torch.inference_mode():
            probabilities = F.softmax(self._load_model()(inputs.to("cpu")), dim=1)
        grade_index = int(probabilities.argmax(1)[0])
        data[self.output_label_key] = MetaTensor(probabilities[0].cpu())
        data[self.output_json_key] = {
            "status": "ok",
            "dr_grade": grade_index,
            "dr_label": DINO2_DR_CLASSES[grade_index],
            "dr_probability": float(probabilities[0, grade_index]),
            "dr_all_probabilities": {
                DINO2_DR_CLASSES[index]: float(probabilities[0, index]) for index in range(5)
            },
            "model_id": "CASALab-Unisa/Dino2-DR",
            "model_commit": OFFICIAL_COMMIT,
            "checkpoint_name": Path(self.checkpoint_path).name,
            "calibration_status": "not_locally_calibrated",
            "preprocessing_version": "dino2-dr-official-512-resize504-v1",
            "device": "cpu",
        }
        return data

    def run_invert_transforms(self, data, pre_transforms, transforms):
        return data

    def post_transforms(self, data=None):
        return []
