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
                data[key] = img
            else:
                while img.ndim > 3 and img.shape[-1] == 1:
                    img = img.squeeze(-1)
                data[key] = img

            if hasattr(img, "meta") and img.meta is not None:
                ss = img.meta.get("spatial_shape")
                if ss is not None and len(ss) > 2 and ss[-1] == 1:
                    img.meta["spatial_shape"] = ss[:-1]

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
