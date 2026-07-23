import json
import logging
import os
import threading
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image
from monai.transforms import EnsureChannelFirstd, EnsureTyped, LoadImaged
from monailabel.interfaces.tasks.infer_v2 import InferTask, InferType

from .fovea_detection import loaded_image_to_rgb

logger = logging.getLogger(__name__)

MODEL_NAME = "NCBI DeepSeeNet+"
RISK_FACTORS = {
    "drusen": ("none_small", "intermediate", "large"),
    "pigment": ("absent", "present"),
    "amd": ("absent", "advanced"),
}
_MODEL_CACHE: Dict[str, object] = {}
_MODEL_LOCK = threading.RLock()


def _parse_fovea(value) -> Optional[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, dict):
        return None
    try:
        x_px, y_px = float(value["x_px"]), float(value["y_px"])
    except (KeyError, TypeError, ValueError):
        return None
    if not np.isfinite(x_px) or not np.isfinite(y_px):
        return None
    return {**value, "x_px": x_px, "y_px": y_px}


def crop_fovea_centered(image: Image.Image, x_px: float, y_px: float) -> Tuple[Image.Image, dict]:
    """Translate the official square crop so that the fovea is at its center.

    The crop scale remains min(width, height). Missing source pixels are black,
    which keeps the fovea centered instead of silently shifting the crop.
    """
    width, height = image.size
    side = min(width, height)
    left = int(round(x_px - side / 2.0))
    top = int(round(y_px - side / 2.0))
    right, bottom = left + side, top + side

    src_left, src_top = max(0, left), max(0, top)
    src_right, src_bottom = min(width, right), min(height, bottom)
    canvas = Image.new("RGB", (side, side), (0, 0, 0))
    if src_right > src_left and src_bottom > src_top:
        region = image.crop((src_left, src_top, src_right, src_bottom))
        canvas.paste(region, (src_left - left, src_top - top))

    geometry = {
        "crop_box": {"left": left, "top": top, "right": right, "bottom": bottom},
        "padding": {
            "left": max(0, -left),
            "top": max(0, -top),
            "right": max(0, right - width),
            "bottom": max(0, bottom - height),
        },
        "source_width": width,
        "source_height": height,
    }
    return canvas, geometry


def crop_center_square(image: Image.Image) -> Tuple[Image.Image, dict]:
    width, height = image.size
    side = min(width, height)
    left = int(round((width - side) / 2.0))
    top = int(round((height - side) / 2.0))
    geometry = {
        "crop_box": {"left": left, "top": top, "right": left + side, "bottom": top + side},
        "padding": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "source_width": width,
        "source_height": height,
    }
    return image.crop((left, top, left + side, top + side)), geometry


def preprocess_deepseenet(image_rgb: np.ndarray, fovea=None):
    from tensorflow.keras.applications.inception_v3 import preprocess_input

    image = Image.fromarray(loaded_image_to_rgb(image_rgb), mode="RGB")
    parsed_fovea = _parse_fovea(fovea)
    if parsed_fovea is not None:
        cropped, geometry = crop_fovea_centered(image, parsed_fovea["x_px"], parsed_fovea["y_px"])
        mode = "fovea_centered"
    else:
        cropped, geometry = crop_center_square(image)
        mode = "central_crop_fallback"
    resized = cropped.resize((512, 512), Image.Resampling.BILINEAR)
    tensor = np.expand_dims(np.asarray(resized, dtype=np.float32), axis=0)
    return preprocess_input(tensor), mode, geometry, parsed_fovea


def _load_models(model_folder: str):
    import tensorflow as tf

    with _MODEL_LOCK:
        if _MODEL_CACHE:
            return _MODEL_CACHE
        # DeepSeeNet+ intentionally runs on CPU alongside the PyTorch GPU tasks.
        try:
            tf.config.set_visible_devices([], "GPU")
        except RuntimeError:
            logger.warning("TensorFlow devices were already initialized; CPU-only selection was not applied")
        for risk_factor in RISK_FACTORS:
            path = os.path.join(model_folder, f"{risk_factor}.h5")
            if not os.path.isfile(path):
                raise FileNotFoundError(f"DeepSeeNet+ model not found: {path}")
            logger.info("Loading DeepSeeNet+ model %s", path)
            _MODEL_CACHE[risk_factor] = tf.keras.models.load_model(path, compile=False)
        return _MODEL_CACHE


def predict_deepseenet(image_rgb: np.ndarray, model_folder: str, fovea=None, fovea_error=None) -> dict:
    inputs, mode, geometry, parsed_fovea = preprocess_deepseenet(image_rgb, fovea=fovea)
    models = _load_models(model_folder)
    result = {
        "status": "ok" if mode == "fovea_centered" else "ok_with_fallback",
        "preprocessing_mode": mode,
        "fovea": parsed_fovea,
        "preprocessing": geometry,
        "model": MODEL_NAME,
    }
    if mode == "central_crop_fallback":
        result["fovea_error"] = str(fovea_error or "fovea unavailable")[:500]

    with _MODEL_LOCK:
        for risk_factor, labels in RISK_FACTORS.items():
            probabilities = np.asarray(models[risk_factor].predict(inputs, verbose=0))[0].astype(float)
            class_index = int(np.argmax(probabilities))
            result[risk_factor] = {
                "class_index": class_index,
                "label": labels[class_index],
                "probability": round(float(probabilities[class_index]), 6),
                "probabilities": [round(float(value), 6) for value in probabilities],
            }
    return result


class DeepSeeNetPlus(InferTask):
    def __init__(self, model_folder: str):
        super().__init__(
            type=InferType.CLASSIFICATION,
            labels={},
            dimension=2,
            description="DeepSeeNet+ AMD risk factors",
        )
        self.model_folder = model_folder

    def is_valid(self) -> bool:
        return all(os.path.isfile(os.path.join(self.model_folder, f"{name}.h5")) for name in RISK_FACTORS)

    def __call__(self, request):
        data = LoadImaged(keys="image")({"image": request["image"]})
        data = EnsureChannelFirstd(keys="image")(data)
        data = EnsureTyped(keys="image", device="cpu")(data)
        rgb = loaded_image_to_rgb(data["image"])
        result = predict_deepseenet(
            rgb,
            self.model_folder,
            fovea=request.get("fovea"),
            fovea_error=request.get("fovea_error"),
        )
        return None, {"deepseenet_plus": result, "model_status": {"deepseenet_plus": "loaded"}}
