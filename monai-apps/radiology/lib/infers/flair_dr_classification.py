import logging
import os
import time
from typing import Callable, Sequence

import numpy as np
import torch
from monai.data import MetaTensor
from monai.inferers import Inferer, SimpleInferer
from monai.transforms import LoadImaged, MapTransform

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask

from .clip_dr_classification import _to_rgb_uint8

logger = logging.getLogger(__name__)

FLAIR_DR_CLASSES = {
    0: "no_dr",
    1: "mild_npdr",
    2: "moderate_npdr",
    3: "severe_npdr",
    4: "proliferative_dr",
}

# Official FLAIR zero-shot targets used by its transferability experiments.
FLAIR_DR_PROMPTS = [
    "no diabetic retinopathy",
    "mild diabetic retinopathy",
    "moderate diabetic retinopathy",
    "severe diabetic retinopathy",
    "proliferative diabetic retinopathy",
]

OFFICIAL_REPOSITORY = "jusiro/FLAIR"
OFFICIAL_COMMIT = "d6652d53389ff49e5f73efaccf4246e9de88d1a3"


class FlairDRPreprocessd(MapTransform):
    def __call__(self, data):
        result = dict(data)
        for key in self.keys:
            result[key] = _to_rgb_uint8(result[key])
        return result


class FlairDRClassification(BasicInferTask):
    def __init__(
        self,
        path,
        network=None,
        type=InferType.CLASSIFICATION,
        labels=None,
        dimension=2,
        description="FLAIR zero-shot five-grade diabetic retinopathy classification",
        **kwargs,
    ):
        super().__init__(
            path=path,
            network=network,
            type=type,
            labels=labels,
            dimension=dimension,
            description=description,
            load_strict=True,
            **kwargs,
        )
        self.model_id = os.environ.get("FLAIR_MODEL_ID", "jusiro2/FLAIR")
        self._model = None
        self._text_embeddings = None

    def is_valid(self) -> bool:
        return True

    def pre_transforms(self, data=None) -> Sequence[Callable]:
        return [LoadImaged(keys="image"), FlairDRPreprocessd(keys="image")]

    def inferer(self, data=None) -> Inferer:
        return SimpleInferer()

    def _load_model(self):
        if self._model is None:
            from flair import FLAIRModel

            logger.info("Loading FLAIR foundation model from Hugging Face: %s", self.model_id)
            self._model = FLAIRModel.from_pretrained(self.model_id)
            self._model.eval()
            # Reproduce the official DR zero-shot evaluation with expert descriptions.
            _, self._text_embeddings = self._model.compute_text_embeddings(
                FLAIR_DR_PROMPTS,
                domain_knowledge=True,
            )
        return self._model

    def run_inferer(self, data, convert_to_batch=True, device="cpu"):
        started = time.perf_counter()
        model = self._load_model()
        image = data[self.input_key]
        if torch.is_tensor(image):
            image = image.detach().cpu().numpy()
        image = np.asarray(image, dtype=np.uint8)

        with torch.inference_mode():
            image_tensor = model.preprocess_image(image)
            image_embeddings = model.vision_model(image_tensor)
            logits = model.compute_logits(
                image_embeddings,
                self._text_embeddings.to(image_embeddings.device),
            )
            probabilities = torch.softmax(logits, dim=-1)[0].detach().cpu().numpy().astype(np.float32)
        grade_index = int(np.argmax(probabilities))
        confidence = float(probabilities[grade_index])
        all_probabilities = {
            FLAIR_DR_CLASSES[index]: float(probabilities[index]) for index in range(5)
        }

        data[self.output_label_key] = MetaTensor(torch.from_numpy(probabilities))
        data[self.output_json_key] = {
            "dr_grade": grade_index,
            "dr_label": FLAIR_DR_CLASSES[grade_index],
            "dr_probability": confidence,
            "dr_all_probabilities": all_probabilities,
            "status": "ok",
            "model_id": self.model_id,
            "model_commit": OFFICIAL_COMMIT,
            "backbone": "FLAIR ResNet-50 + Bio_ClinicalBERT",
            "classification_method": "zero_shot",
            "domain_knowledge_prompts": True,
            "zero_shot_prompts": list(FLAIR_DR_PROMPTS),
            "calibration_status": "not_locally_calibrated",
            "preprocessing_version": "flair-official-canvas512-v1",
            "inference_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "device": str(next(model.parameters()).device),
        }
        return data

    def run_invert_transforms(self, data, pre_transforms, transforms):
        return data

    def post_transforms(self, data=None) -> Sequence[Callable]:
        return []
