import logging
from typing import Any, Callable, Dict, Sequence

import torch
import torch.nn.functional as F
from monai.inferers import Inferer, SimpleInferer
from monai.transforms import (
    AsDiscreted,
    EnsureChannelFirstd,
    EnsureTyped,
    LoadImaged,
    Resized,
    ScaleIntensityRanged,
)
from transformers import SegformerForSemanticSegmentation, AutoImageProcessor

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask
from monailabel.transform.post import Restored

logger = logging.getLogger(__name__)


def _quality_score_chw_slice(img):
    """Estimate retinal image quality for choosing one slice from a DICOM series."""
    tensor = img.detach().float().cpu() if isinstance(img, torch.Tensor) else torch.as_tensor(img).float()
    if tensor.dim() != 3:
        return float("-inf")
    if tensor.shape[0] == 1:
        gray = tensor[0]
    elif tensor.shape[0] == 3:
        gray = 0.299 * tensor[0] + 0.587 * tensor[1] + 0.114 * tensor[2]
    else:
        return float("-inf")

    if gray.numel() and float(gray.max()) <= 1.0:
        gray = gray * 255.0
    gray = gray.clamp(0, 255)
    foreground = gray > 8
    foreground_ratio = float(foreground.float().mean())
    if foreground_ratio < 0.05:
        return float("-inf")

    fg = gray[foreground]
    contrast = float(fg.std()) if fg.numel() > 1 else 0.0
    exposure_penalty = abs(float(fg.mean()) - 115.0) if fg.numel() else 115.0
    saturated = float(((fg <= 3) | (fg >= 252)).float().mean()) if fg.numel() else 1.0

    dx = gray[:, 1:] - gray[:, :-1]
    dy = gray[1:, :] - gray[:-1, :]
    sharpness = float(dx.var() + dy.var())

    return (
        torch.log1p(torch.tensor(sharpness)).item() * 20.0
        + contrast
        + foreground_ratio * 25.0
        - exposure_penalty * 0.15
        - saturated * 50.0
    )


class OpticDiscCup(BasicInferTask):
    def __init__(
        self,
        path,
        network=None,
        type=InferType.SEGMENTATION,
        labels=None,
        dimension=2,
        description="SegFormer-based optic disc and cup segmentation (REFUGE dataset)",
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
        self.model_id = "pamixsun/segformer_for_optic_disc_cup_segmentation"
        self._hf_model = None
        self._hf_processor = None

    def _load_hf_model(self, device):
        if self._hf_model is None:
            logger.info(f"Loading SegFormer OD/OC model from HuggingFace: {self.model_id}")
            self._hf_processor = AutoImageProcessor.from_pretrained(self.model_id)
            self._hf_model = SegformerForSemanticSegmentation.from_pretrained(self.model_id)
            self._hf_model.eval()
        self._hf_model.to(device)
        return self._hf_model

    def _get_network(self, device, data):
        return self._load_hf_model(device)

    def is_valid(self) -> bool:
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
            ImageNetNormalized(keys="image"),
        ]

    def inferer(self, data=None) -> Inferer:
        return SimpleInferer()

    def run_inferer(self, data, convert_to_batch=True, device="cuda"):
        network = self._get_network(device, data)
        inputs = data[self.input_key]
        inputs = inputs if torch.is_tensor(inputs) else torch.from_numpy(inputs)
        inputs = inputs[None] if convert_to_batch else inputs
        inputs = inputs.to(torch.device(device))

        with torch.no_grad():
            outputs = network(inputs)

        logits = outputs.logits
        if convert_to_batch:
            logits = logits[0]

        data[self.output_label_key] = logits
        data[self.output_json_key] = {
            "label_info": [
                {"name": "optic_disc", "color": [0, 255, 0]},
                {"name": "optic_cup", "color": [255, 0, 0]},
            ]
        }
        logger.info(f"=== DEBUG run_inferer: data keys after = {list(data.keys())}")
        logger.info(f"=== DEBUG run_inferer: result = {data.get(self.output_json_key)}")
        return data

    def inverse_transforms(self, data=None):
        return []

    def post_transforms(self, data=None) -> Sequence[Callable]:
        return [
            EnsureTyped(keys="pred", device=data.get("device") if data else None),
            AsDiscreted(keys="pred", argmax=True),
            Restored(keys="pred", ref_image="image"),
        ]


class Ensure3ChannelRGBd:
    def __init__(self, keys):
        self.keys = keys if isinstance(keys, (list, tuple)) else [keys]

    def __call__(self, data):
        for key in self.keys:
            img = data[key]
            if isinstance(img, torch.Tensor):
                if img.shape[0] == 1:
                    img = img.repeat(3, 1, 1, 1) if img.dim() == 4 else img.repeat(3, 1, 1)
                data[key] = img
            else:
                if img.shape[0] == 1:
                    img = img.repeat(3, axis=0)
                data[key] = img
        return data


class SqueezeDepthd:
    def __init__(self, keys):
        self.keys = keys if isinstance(keys, (list, tuple)) else [keys]

    def __call__(self, data):
        for key in self.keys:
            img = data[key]
            if isinstance(img, torch.Tensor):
                while img.dim() > 3 and img.shape[-1] == 1:
                    img = img.squeeze(-1)
                if img.dim() == 4 and img.shape[0] in (1, 3):
                    scores = [_quality_score_chw_slice(img[..., index]) for index in range(img.shape[-1])]
                    best_index = int(torch.tensor(scores).argmax().item())
                    logger.info(
                        "Selected best 2D slice %s/%s for %s; scores=%s",
                        best_index + 1,
                        img.shape[-1],
                        key,
                        [round(float(score), 3) for score in scores],
                    )
                    img = img[..., best_index]
                data[key] = img
            else:
                while img.ndim > 3 and img.shape[-1] == 1:
                    img = img.squeeze(-1)
                if img.ndim == 4 and img.shape[0] in (1, 3):
                    scores = [_quality_score_chw_slice(img[..., index]) for index in range(img.shape[-1])]
                    best_index = int(torch.tensor(scores).argmax().item())
                    logger.info(
                        "Selected best 2D slice %s/%s for %s; scores=%s",
                        best_index + 1,
                        img.shape[-1],
                        key,
                        [round(float(score), 3) for score in scores],
                    )
                    img = img[..., best_index]
                data[key] = img

            if hasattr(img, "meta") and img.meta is not None:
                ss = img.meta.get("spatial_shape")
                if ss is not None and len(ss) > 2 and ss[-1] == 1:
                    img.meta["spatial_shape"] = ss[:-1]
                elif ss is not None and len(ss) > 2 and img.dim() == 3:
                    img.meta["spatial_shape"] = ss[:2]

        return data


class ImageNetNormalized:
    def __init__(self, keys):
        self.keys = keys if isinstance(keys, (list, tuple)) else [keys]
        self.mean = [0.485, 0.456, 0.406]
        self.std = [0.229, 0.224, 0.225]

    def __call__(self, data):
        for key in self.keys:
            img = data[key]
            if isinstance(img, torch.Tensor):
                for c in range(3):
                    img[c] = (img[c] - self.mean[c]) / self.std[c]
            else:
                for c in range(3):
                    img[c] = (img[c] - self.mean[c]) / self.std[c]
            data[key] = img
        return data
