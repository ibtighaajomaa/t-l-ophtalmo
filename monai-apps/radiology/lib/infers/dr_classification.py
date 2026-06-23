import logging
from typing import Callable, Sequence

import torch
import torch.nn.functional as F
from monai.inferers import Inferer, SimpleInferer
from monai.transforms import (
    EnsureChannelFirstd,
    EnsureTyped,
    LoadImaged,
    Resized,
    ScaleIntensityRanged,
)
from transformers import AutoModelForImageClassification, ViTImageProcessor

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask
from .optic_disc_cup import Ensure3ChannelRGBd, SqueezeDepthd

logger = logging.getLogger(__name__)

DR_CLASSES = {
    0: "No DR",
    1: "Mild NPDR",
    2: "Moderate NPDR",
    3: "Severe NPDR",
    4: "Proliferative DR",
}


class DRClassification(BasicInferTask):
    def __init__(
        self,
        path,
        network=None,
        type=InferType.CLASSIFICATION,
        labels=None,
        dimension=2,
        description="ViT-based diabetic retinopathy classification (APTOS 2019)",
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
        self.model_id = "Kontawat/vit-diabetic-retinopathy-classification"
        self._hf_model = None
        self._hf_processor = None

    def _load_hf_model(self, device):
        if self._hf_model is None:
            logger.info(f"Loading ViT DR model from HuggingFace: {self.model_id}")
            self._hf_processor = ViTImageProcessor.from_pretrained(self.model_id)
            self._hf_model = AutoModelForImageClassification.from_pretrained(self.model_id)
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
            Resized(keys="image", spatial_size=(224, 224), mode="bilinear"),
            ScaleIntensityRanged(keys="image", a_min=0, a_max=255, b_min=0.0, b_max=1.0, clip=True),
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
        probs = F.softmax(logits, dim=1)
        pred_class = int(torch.argmax(probs, dim=1)[0].cpu())
        dr_label = DR_CLASSES[pred_class]
        dr_prob = float(probs[0, pred_class].cpu())
        all_probs = {str(DR_CLASSES[i]): float(probs[0, i].cpu()) for i in range(5)}

        logger.info(f"DR Classification: {dr_label} (confidence={dr_prob:.4f})")

        data[self.output_label_key] = probs[0].cpu()
        data[self.output_json_key] = {
            "dr_grade": pred_class,
            "dr_label": dr_label,
            "dr_probability": dr_prob,
            "dr_all_probabilities": all_probs,
            "label_info": [
                {"name": "no_dr", "color": [0, 255, 0]},
                {"name": "mild_npdr", "color": [255, 255, 0]},
                {"name": "moderate_npdr", "color": [255, 165, 0]},
                {"name": "severe_npdr", "color": [255, 100, 0]},
                {"name": "proliferative_dr", "color": [255, 0, 0]},
            ]
        }
        return data

    def run_invert_transforms(self, data, pre_transforms, transforms):
        return data

    def post_transforms(self, data=None) -> Sequence[Callable]:
        return []
