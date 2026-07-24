import hashlib
import logging
import os
from typing import Sequence, Union

import numpy as np
import torch

logger = logging.getLogger(__name__)

BIGEYE_COMMIT = "c09dbc164507872eb7c8b7f57c91b7ba4fdd289f"
BIGEYE_SHA256 = "f4c3c89a4da02b84af6cc85b4ee9cd4be35bf2c836cf230b0a6d06a3805b646b"
BIGEYE_MODEL_ID = f"Janga-Lab/BigEye@{BIGEYE_COMMIT}"
BIGEYE_INPUT_SHAPE = (None, 512, 512, 3)
BIGEYE_OUTPUT_SHAPE = (None, 512, 512, 7)

LESION_NAMES = {
    1: "microaneurysms",
    2: "hard_exudates",
    3: "cotton_wool_spots",
    4: "hemorrhages",
    5: "neovascularization",
    6: "laser_scars",
}

LESION_COLORS = {
    1: (168, 85, 247),
    2: (255, 217, 61),
    3: (80, 200, 255),
    4: (255, 70, 70),
    5: (255, 80, 180),
    6: (80, 220, 140),
}


def find_model_path(paths: Union[str, Sequence[str]]) -> str:
    candidates = paths if isinstance(paths, (list, tuple)) else [paths]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "BigEye checkpoint not found. Run tools/setup_bigeye.sh and set "
        "BIGEYE_MODEL_PATH if the checkpoint is stored elsewhere."
    )


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_file(path: str) -> None:
    actual = sha256_file(path)
    if actual != BIGEYE_SHA256:
        raise ValueError(
            f"Invalid BigEye checkpoint SHA-256 for {path}: expected "
            f"{BIGEYE_SHA256}, got {actual}"
        )


def _to_rgb_hwc(image) -> np.ndarray:
    if isinstance(image, torch.Tensor):
        image = image.detach().cpu().numpy()
    image = np.asarray(image)
    if image.ndim == 4 and image.shape[0] in (1, 3):
        image = image[..., 0]
    if image.ndim != 3:
        raise ValueError(f"Expected a 3D fundus image, got shape {image.shape}")
    if image.shape[0] in (1, 3):
        image = np.transpose(image, (1, 2, 0))
    if image.shape[-1] == 1:
        image = np.repeat(image, 3, axis=-1)
    if image.shape[-1] != 3:
        raise ValueError(f"Expected 3 color channels, got shape {image.shape}")
    if np.issubdtype(image.dtype, np.floating) and image.size and image.max() <= 1.0:
        image = image * 255.0
    return np.clip(image, 0, 255).astype(np.uint8)


def preprocess_bigeye_image(image) -> np.ndarray:
    """Reproduce BigEye's OpenCV BGR + LAB CLAHE preprocessing."""
    import cv2

    rgb = _to_rgb_hwc(image)
    bgr = np.ascontiguousarray(rgb[..., ::-1])
    bgr = cv2.resize(bgr, (512, 512), interpolation=cv2.INTER_LINEAR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lightness, green_red, blue_yellow = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = cv2.merge((clahe.apply(lightness), green_red, blue_yellow))
    bgr = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    return np.expand_dims(bgr.astype(np.float32) / 255.0, axis=0)


def load_bigeye_model(paths):
    import tensorflow as tf

    path = find_model_path(paths)
    verify_model_file(path)
    logger.info("Loading BigEye lesion model from %s", path)
    try:
        model = tf.keras.models.load_model(path, compile=False)
    except Exception as exc:
        raise RuntimeError(
            "BigEye checkpoint could not be loaded. It requires the pinned "
            "TensorFlow/Keras runtime from the radiology image."
        ) from exc
    if tuple(model.input_shape) != BIGEYE_INPUT_SHAPE:
        raise ValueError(f"Unexpected BigEye input shape: {model.input_shape}")
    if tuple(model.output_shape) != BIGEYE_OUTPUT_SHAPE:
        raise ValueError(f"Unexpected BigEye output shape: {model.output_shape}")
    return model


def predict_bigeye(model, image) -> np.ndarray:
    inputs = preprocess_bigeye_image(image)
    probabilities = np.asarray(model.predict(inputs, verbose=0))
    if probabilities.shape != (1, 512, 512, 7):
        raise ValueError(f"Invalid BigEye prediction shape: {probabilities.shape}")
    if not np.all(np.isfinite(probabilities)):
        raise ValueError("BigEye prediction contains non-finite values")
    return np.argmax(probabilities[0], axis=-1).astype(np.uint8)


def model_metadata():
    return {
        "model_id": BIGEYE_MODEL_ID,
        "model_commit": BIGEYE_COMMIT,
        "checkpoint_sha256": BIGEYE_SHA256,
    }


def quantify_lesion_mask(mask: np.ndarray):
    import cv2

    mask = np.asarray(mask).squeeze()
    if mask.ndim != 2:
        raise ValueError(f"Expected a 2D lesion mask, got shape {mask.shape}")
    if mask.size and (mask.min() < 0 or mask.max() > 6):
        raise ValueError("BigEye lesion mask contains an unknown class")

    def region_count(class_id):
        binary = np.ascontiguousarray(mask == class_id, dtype=np.uint8)
        components, _ = cv2.connectedComponents(binary, connectivity=8)
        return max(0, int(components) - 1)

    counts = {name: region_count(class_id) for class_id, name in LESION_NAMES.items()}
    pixel_counts = {
        name: int(np.sum(mask == class_id)) for class_id, name in LESION_NAMES.items()
    }
    total = int(mask.size)
    lesion_pixels = int(np.sum(mask > 0))
    return {
        **counts,
        "exudates": counts["hard_exudates"] + counts["cotton_wool_spots"],
        "pixel_counts": pixel_counts,
        "coverage_pct": round(lesion_pixels / total * 100, 2) if total else 0.0,
        **model_metadata(),
    }
