import base64
import copy
import io
import logging
import os
from typing import Any, Dict, Sequence, Tuple, Union

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from monai.transforms import (
    EnsureChannelFirstd,
    EnsureTyped,
    LoadImaged,
    Resized,
    ScaleIntensityRanged,
)
from monailabel.interfaces.tasks.infer_v2 import InferTask, InferType
from monailabel.utils.others.generic import device_list
from transformers import SegformerForSemanticSegmentation, AutoImageProcessor
from .fovea_detection import detect_fovea_rgb, loaded_image_to_rgb
from .lesion_seg import suppress_macular_zone_lesions, suppress_optic_disc_lesions
LESION_NAMES = {1: "hard_exudates", 2: "hemorrhages", 3: "microaneurysms", 4: "soft_exudates"}
LESION_COLORS = {
    1: (160, 160, 160), 2: (50, 50, 255), 3: (106, 13, 173), 4: (255, 0, 140)
}

logger = logging.getLogger(__name__)

OD_OC_COLORS = {
    1: (0, 255, 0),
    2: (255, 0, 0),
}

VESSEL_COLOR = (0, 200, 255)

ODOC_MODEL_ID = "pamixsun/segformer_for_optic_disc_cup_segmentation"


class CompositeSegmenter(InferTask):
    def __init__(
        self,
        lesion_model_path: Union[str, Sequence[str]],
        vessel_model_path: Union[str, Sequence[str]],
        vessel_network: torch.nn.Module,
        lesion_network: torch.nn.Module,
        lesion_labels: Dict[Any, Any],
        vessel_labels: Dict[Any, Any],
        odoc_labels: Dict[Any, Any],
        fovea_model_path: str = None,
        preload: bool = False,
    ):
        super().__init__(
            type=InferType.SEGMENTATION,
            labels={**odoc_labels, **lesion_labels, **vessel_labels},
            dimension=2,
            description="Composite fundus segmentation: OD/OC + lesions + vessels + overlay",
        )
        self.lesion_model_path = lesion_model_path if isinstance(lesion_model_path, list) else [lesion_model_path]
        self.vessel_model_path = vessel_model_path if isinstance(vessel_model_path, list) else [vessel_model_path]
        self.vessel_network = vessel_network
        self.lesion_network = lesion_network
        self.lesion_labels = lesion_labels
        self.vessel_labels = vessel_labels
        self.odoc_labels = odoc_labels
        self.fovea_model_path = fovea_model_path

        self._odoc_model = None
        self._odoc_processor = None
        self._lesion_model = None

        if preload:
            for device in device_list():
                self._load_models(device)

    def _load_odoc(self, device):
        if self._odoc_model is None:
            logger.info(f"Loading SegFormer OD/OC from HuggingFace: {ODOC_MODEL_ID}")
            self._odoc_processor = AutoImageProcessor.from_pretrained(ODOC_MODEL_ID)
            self._odoc_model = SegformerForSemanticSegmentation.from_pretrained(ODOC_MODEL_ID)
            self._odoc_model.eval()
        self._odoc_model.to(device)
        return self._odoc_model

    def _load_checkpoint(self, paths, network, device):
        for p in reversed(paths):
            if p and os.path.exists(p):
                logger.info(f"Loading model from: {p}")
                model = copy.deepcopy(network)
                model.to(device)
                checkpoint = torch.load(p, map_location=torch.device(device), weights_only=True)
                state_dict = checkpoint.get("model_state_dict", checkpoint)
                if any(k.startswith("model.") for k in state_dict):
                    state_dict = {k.replace("model.", "", 1): v for k, v in state_dict.items()}
                missing, unexpected = model.load_state_dict(state_dict, strict=False)
                if missing:
                    logger.warning(f"Missing keys: {missing}")
                if unexpected:
                    logger.warning(f"Unexpected keys: {unexpected}")
                model.eval()
                return model
        logger.warning(f"No checkpoint found at {paths}")
        return None

    def _load_models(self, device):
        logger.info("Loading all models for composite segmentation")
        odoc = self._load_odoc(device)
        if self._lesion_model is None:
            self._lesion_model = self._load_checkpoint(self.lesion_model_path, self.lesion_network, device)
        lesion = self._lesion_model
        vessel = self._load_checkpoint(self.vessel_model_path, self.vessel_network, device)
        return odoc, lesion, vessel

    def is_valid(self) -> bool:
        lesion_ok = any(os.path.exists(p) for p in self.lesion_model_path)
        vessel_ok = any(os.path.exists(p) for p in self.vessel_model_path)
        return lesion_ok and vessel_ok

    def _load_image(self, request) -> np.ndarray:
        loader = LoadImaged(keys="image")
        ch_first = EnsureChannelFirstd(keys="image")
        typed = EnsureTyped(keys="image", device="cpu")
        data = loader({"image": request["image"]})
        data = ch_first(data)
        data = typed(data)
        img = data["image"]
        if isinstance(img, torch.Tensor):
            img = img.cpu().numpy()
        if img.shape[0] == 1:
            img = np.repeat(img, 3, axis=0)
        while img.ndim > 3 and img.shape[-1] == 1:
            img = img.squeeze(-1)
        # MONAI loads a multi-instance OP series as C×H×W×N. The composite
        # models operate on one 2D fundus photograph at a time, matching the
        # source image selected in OHIF.
        if img.ndim > 3 and img.shape[0] in (1, 3, 4):
            img = img.reshape(img.shape[0], img.shape[1], img.shape[2], -1)[..., 0]
        return img

    def _preprocess(self, image: np.ndarray, size=512, normalize=True):
        img = image.copy()
        img = img.astype(np.float32)
        resized = Resized(keys="image", spatial_size=(size, size), mode="bilinear")
        data = {"image": img}
        if normalize:
            scale = ScaleIntensityRanged(
                keys="image", a_min=0, a_max=255, b_min=0.0, b_max=1.0, clip=True
            )
            data = scale(data)
        data = resized(data)
        processed = data["image"]
        if isinstance(processed, torch.Tensor):
            processed = processed.detach().cpu().numpy()
        return np.asarray(processed)

    def _run_odoc(self, image_np: np.ndarray, device):
        model = self._load_odoc(device)
        img_hwc = (np.transpose(image_np, (1, 2, 0)) * 255).astype(np.uint8)
        from PIL import Image as PILImage
        pil_image = PILImage.fromarray(img_hwc)
        inputs = self._odoc_processor(images=pil_image, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model(**inputs)
        h, w = image_np.shape[1], image_np.shape[2]
        logits = F.interpolate(outputs.logits, size=(h, w), mode="bilinear", align_corners=False)
        pred = logits.argmax(dim=1)[0].cpu().numpy()
        return pred

    def _run_lesion(self, image_np: np.ndarray, model, device):
        if model is None:
            return np.zeros(image_np.shape[1:], dtype=np.uint8)
        tensor = torch.from_numpy(image_np).unsqueeze(0).float().to(device)
        with torch.no_grad():
            return torch.softmax(model(tensor), dim=1).argmax(dim=1)[0].cpu().numpy().astype(np.uint8)

    def _run_vessel(self, image_np: np.ndarray, model, device):
        if model is None:
            h, w = image_np.shape[1], image_np.shape[2]
            return np.zeros((h, w), dtype=np.uint8), np.zeros((h, w))
        tensor = torch.from_numpy(image_np).unsqueeze(0).float().to(device)
        with torch.no_grad():
            logits = model(tensor).cpu().numpy()[0]
        prob = 1.0 / (1.0 + np.exp(-logits[0]))
        mask = (prob > 0.5).astype(np.uint8)
        return mask, prob

    @staticmethod
    def _compute_vcdr(od_mask, oc_mask):
        od_rows = np.where(od_mask.any(axis=1))[0]
        oc_rows = np.where(oc_mask.any(axis=1))[0]
        if len(od_rows) == 0 or len(oc_rows) == 0:
            return 0.0
        od_height = od_rows[-1] - od_rows[0] + 1
        oc_height = oc_rows[-1] - oc_rows[0] + 1
        if od_height == 0:
            return 0.0
        return min(oc_height / od_height, 1.0)

    def _resize_mask(self, mask: np.ndarray, w: int, h: int) -> np.ndarray:
        return np.array(
            Image.fromarray(mask.astype(np.uint8)).resize((w, h), Image.NEAREST)
        )

    def _draw_contour(self, overlay: np.ndarray, mask: np.ndarray, color, thickness=3):
        coords = np.argwhere(mask)
        if len(coords) == 0:
            return
        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
        for dy in range(-thickness, thickness + 1):
            for dx in range(-thickness, thickness + 1):
                if abs(dy) + abs(dx) > thickness:
                    continue
                y_edges = np.concatenate([coords[:, 0] + dy])
                x_edges = np.concatenate([coords[:, 1] + dx])
                valid = (
                    (y_edges >= 0) & (y_edges < overlay.shape[0]) &
                    (x_edges >= 0) & (x_edges < overlay.shape[1])
                )
                overlay[y_edges[valid], x_edges[valid]] = color

    def _create_overlay(self, image_rgb: np.ndarray, odoc_pred, lesion_pred, vessel_mask, fovea=None):
        h, w = image_rgb.shape[:2]
        overlay = image_rgb.copy()

        # Lesion overlay
        if lesion_pred is not None and lesion_pred.max() > 0:
            lesion_resized = self._resize_mask(lesion_pred, w, h)
            for cls_id, color in LESION_COLORS.items():
                mask = lesion_resized == cls_id
                if mask.any():
                    overlay[mask] = (
                        overlay[mask].astype(np.float32) * 0.6 +
                        np.array(color, dtype=np.float32) * 0.4
                    ).astype(np.uint8)

        # OD/OC overlay — draw contour around mask boundary
        if odoc_pred is not None:
            odoc_resized = self._resize_mask(odoc_pred, w, h)
            for cls_id, color in OD_OC_COLORS.items():
                mask = odoc_resized == cls_id
                if mask.any():
                    self._draw_contour(overlay, mask, color, thickness=3)

        # Vessel overlay
        if vessel_mask is not None and vessel_mask.max() > 0:
            vessel_resized = self._resize_mask(vessel_mask, w, h).astype(bool)
            if vessel_resized.any():
                overlay[vessel_resized] = (
                    overlay[vessel_resized].astype(np.float32) * 0.7 +
                    np.array(VESSEL_COLOR, dtype=np.float32) * 0.3
                ).astype(np.uint8)

        # Fovea point — yellow X in original-image coordinates.
        if fovea:
            x = int(round(float(fovea["x_px"])))
            y = int(round(float(fovea["y_px"])))
            arm = max(8, min(h, w) // 80)
            thickness = max(2, min(h, w) // 400)
            for offset in range(-thickness, thickness + 1):
                for delta in range(-arm, arm + 1):
                    for yy, xx in ((y + delta, x + delta + offset), (y + delta, x - delta + offset)):
                        if 0 <= yy < h and 0 <= xx < w:
                            overlay[yy, xx] = (255, 230, 0)

        return overlay

    def __call__(self, request) -> Tuple[Union[str, None], Dict]:
        device = request.get("device", "cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Composite segmenter using device: {device}")

        odoc_model, lesion_model, vessel_model = self._load_models(device)

        image_np = self._load_image(request)

        orig_h, orig_w = image_np.shape[1], image_np.shape[2]

        # Preprocess for lesion/vessel models (monai transforms)
        lesion_proc = self._preprocess(image_np, size=512, normalize=False)
        vessel_proc = self._preprocess(image_np, size=512, normalize=True)

        # Preprocess for OD/OC (uses raw image via odoc_processor internally)
        odoc_pred = self._run_odoc(image_np, device)

        # Lesions
        lesion_pred = self._run_lesion(lesion_proc, lesion_model, device)
        lesion_pred = suppress_optic_disc_lesions(lesion_pred, odoc_pred)
        lesion_pred = suppress_macular_zone_lesions(lesion_pred)

        # Vessels
        vessel_mask, vessel_prob = self._run_vessel(vessel_proc, vessel_model, device)

        # Resize masks back to original for overlay
        od_mask = (odoc_pred == 1).astype(np.uint8)
        oc_mask = (odoc_pred == 2).astype(np.uint8)
        vcdr = self._compute_vcdr(od_mask, oc_mask)

        if vcdr < 0.3:
            glaucoma_risk = "Faible"
        elif vcdr < 0.5:
            glaucoma_risk = "Modéré"
        elif vcdr < 0.7:
            glaucoma_risk = "Élevé"
        else:
            glaucoma_risk = "Très élevé"

        # Lesion stats
        lesion_stats = {}
        total_pixels = lesion_pred.size
        for cls_id in range(1, 7):
            mask = (lesion_pred == cls_id).astype(np.uint8)
            px = int(mask.sum())
            lesion_stats[str(cls_id)] = {
                "name": LESION_NAMES.get(cls_id, f"class_{cls_id}"),
                "pixel_count": px,
                "percentage": round(px / total_pixels * 100, 4) if total_pixels > 0 else 0.0,
            }

        # Vessel stats
        vessel_density = float(vessel_mask.sum()) / vessel_mask.size * 100 if vessel_mask.size > 0 else 0.0

        # Create the overlay as RGB image (3-channel)
        img_rgb = loaded_image_to_rgb(image_np)
        fovea = None
        fovea_error = None
        if self.fovea_model_path:
            try:
                fovea = detect_fovea_rgb(img_rgb, self.fovea_model_path, device)
            except Exception as exc:
                fovea_error = str(exc)
                logger.warning("Composite fovea localization failed: %s", exc)
        overlay_rgb = self._create_overlay(
            img_rgb, odoc_pred, lesion_pred, vessel_mask, fovea=fovea
        )

        # Encode overlay to base64 PNG
        buf = io.BytesIO()
        Image.fromarray(overlay_rgb).save(buf, format="PNG")
        overlay_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        result_json = {
            "overlay_base64": overlay_b64,
            "overlay_format": "png",
            "overlay_width": orig_w,
            "overlay_height": orig_h,
            "optic_disc_cup": {
                "vcdr": round(vcdr, 3),
                "glaucoma_risk": glaucoma_risk,
                "od_area_pixels": int(od_mask.sum()),
                "oc_area_pixels": int(oc_mask.sum()),
            },
            "lesions": lesion_stats,
            "vessels": {
                "vessel_density": round(vessel_density, 4),
            },
            "fovea": fovea,
            "model_status": {
                "odoc": "loaded",
                "lesion": "loaded",
                "vessel": "loaded" if vessel_model is not None else "not_found",
                "fovea": "loaded" if fovea is not None else f"failed: {fovea_error}",
            },
            "lesion_model": {
                "model_id": "SEBNet-DDR",
                "dataset": "DDR",
            },
        }

        return None, result_json
