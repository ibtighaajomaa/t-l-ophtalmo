import logging
import os
import tempfile
import threading
from typing import Dict, Tuple, Union

import numpy as np
import torch
from PIL import Image
from monai.transforms import EnsureChannelFirstd, EnsureTyped, LoadImaged
from monailabel.interfaces.tasks.infer_v2 import InferTask, InferType

logger = logging.getLogger(__name__)

MODEL_NAME = "Eyened/vascx:fovea/fovea_may26.pt"
_MODEL_CACHE: Dict[Tuple[str, str], object] = {}
_MODEL_LOCK = threading.RLock()


def _select_best_slice(image: np.ndarray) -> np.ndarray:
    if image.ndim != 4 or image.shape[0] not in (1, 3):
        return image
    if image.shape[-1] == 1:
        return image[..., 0]

    scores = []
    for index in range(image.shape[-1]):
        candidate = image[..., index]
        gray = candidate.mean(axis=0)
        foreground = gray > (0.03 if gray.max(initial=0) <= 1.0 else 8)
        scores.append(float(gray[foreground].std()) if foreground.any() else -1.0)
    return image[..., int(np.argmax(scores))]


def loaded_image_to_rgb(image: Union[np.ndarray, torch.Tensor]) -> np.ndarray:
    if isinstance(image, torch.Tensor):
        image = image.detach().cpu().numpy()
    image = np.asarray(image)
    image = _select_best_slice(image)
    image = np.squeeze(image)

    if image.ndim == 2:
        image = np.repeat(image[..., None], 3, axis=-1)
    elif image.ndim == 3 and image.shape[0] in (1, 3, 4):
        image = np.moveaxis(image[:3], 0, -1)
    if image.ndim != 3 or image.shape[-1] not in (1, 3, 4):
        raise ValueError(f"Expected a fundus image, got shape {image.shape}")
    if image.shape[-1] == 1:
        image = np.repeat(image, 3, axis=-1)
    image = image[..., :3].astype(np.float32)
    image = np.nan_to_num(image, nan=0.0, posinf=255.0, neginf=0.0)
    if image.size and float(image.max()) <= 1.0:
        image *= 255.0
    return np.clip(image, 0, 255).astype(np.uint8)


def _get_model(model_path: str, device: torch.device):
    key = (os.path.realpath(model_path), str(device))
    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            if not os.path.isfile(model_path):
                raise FileNotFoundError(f"VascX fovea model not found: {model_path}")
            from rtnls_inference.ensembles import HeatmapRegressionEnsemble

            logger.info("Loading VascX fovea model from %s on %s", model_path, device)
            model = HeatmapRegressionEnsemble.from_torchscript(model_path).to(device)
            model.eval()
            _MODEL_CACHE[key] = model
        return model


def preprocess_fundus_rgb(image_rgb: np.ndarray):
    """Run the official VascX fundus crop and retain its inverse geometry."""
    from rtnls_fundusprep.preprocessor import FundusPreprocessor

    item = FundusPreprocessor(square_size=1024, contrast_enhance=False)(image=image_rgb)
    return loaded_image_to_rgb(item["image"]), item["metadata"]["bounds"]


def restore_fovea_coordinates(x_px: float, y_px: float, bounds: dict) -> Tuple[float, float]:
    """Map a point in the 1024px VascX crop back to the source image."""
    from rtnls_fundusprep.mask_extraction import CFIBounds

    transform, _ = CFIBounds(**bounds).crop(1024)
    restored = transform.apply_inverse(np.asarray([[x_px, y_px]], dtype=np.float32))
    return float(restored[0, 0]), float(restored[0, 1])


def detect_fovea_rgb(image_rgb: np.ndarray, model_path: str, device: Union[str, torch.device]) -> dict:
    image_rgb = loaded_image_to_rgb(image_rgb)
    source_height, source_width = image_rgb.shape[:2]
    if source_width < 2 or source_height < 2:
        raise ValueError("Fundus image is too small for fovea detection")

    requested_device = torch.device(device)
    if requested_device.type == "cuda" and not torch.cuda.is_available():
        requested_device = torch.device("cpu")

    preprocessed_rgb, bounds = preprocess_fundus_rgb(image_rgb)
    model = _get_model(model_path, requested_device)
    with tempfile.TemporaryDirectory(prefix="vascx-fovea-") as temp_dir:
        image_path = os.path.join(temp_dir, "fundus.png")
        Image.fromarray(preprocessed_rgb, mode="RGB").save(image_path)
        with _MODEL_LOCK, torch.inference_mode():
            result = model.predict_preprocessed(
                [{"id": "fundus", "image": image_path}],
                num_workers=0,
                batch_size=1,
            )

    if result is None or result.empty or len(result.columns) < 2:
        raise ValueError("VascX returned no fovea coordinates")
    crop_x, crop_y = (float(result.iloc[0, 0]), float(result.iloc[0, 1]))
    x_px, y_px = restore_fovea_coordinates(crop_x, crop_y, bounds)
    if not np.isfinite(x_px) or not np.isfinite(y_px):
        raise ValueError(f"VascX returned invalid coordinates: {(x_px, y_px)}")
    if not (0 <= x_px < source_width and 0 <= y_px < source_height):
        raise ValueError(
            f"VascX coordinates are outside the source image: {(x_px, y_px)} vs {(source_width, source_height)}"
        )

    return {
        "x_px": round(x_px, 4),
        "y_px": round(y_px, 4),
        "x_normalized": round(x_px / source_width, 6),
        "y_normalized": round(y_px / source_height, 6),
        "source_width": source_width,
        "source_height": source_height,
        "model": MODEL_NAME,
    }


class FoveaDetection(InferTask):
    def __init__(self, model_path: str):
        super().__init__(
            type=InferType.CLASSIFICATION,
            labels={},
            dimension=2,
            description="VascX fovea point localization",
        )
        self.model_path = model_path

    def is_valid(self) -> bool:
        return True

    def __call__(self, request):
        device = request.get("device", "cuda" if torch.cuda.is_available() else "cpu")
        data = LoadImaged(keys="image")({"image": request["image"]})
        data = EnsureChannelFirstd(keys="image")(data)
        data = EnsureTyped(keys="image", device="cpu")(data)
        rgb = loaded_image_to_rgb(data["image"])
        fovea = detect_fovea_rgb(rgb, self.model_path, device)
        return None, {"fovea": fovea, "model_status": {"fovea": "loaded"}}
