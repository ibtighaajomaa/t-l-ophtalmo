import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from monai.inferers import Inferer, SimpleInferer
from monai.data import MetaTensor
from monai.transforms import LoadImaged, MapTransform
from PIL import Image

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask

logger = logging.getLogger(__name__)

CLIP_DR_CLASSES = {
    0: "No DR",
    1: "Mild NPDR",
    2: "Moderate NPDR",
    3: "Severe NPDR",
    4: "Proliferative DR",
}
IMAGENET_MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
OFFICIAL_REPOSITORY = "Qinkaiyu/CLIP-DR"
OFFICIAL_COMMIT = "ca7d88c44f13d0e77bea4b0c2381b51deb75d3c1"


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _to_rgb_uint8(image) -> np.ndarray:
    array = np.asarray(image)
    array = np.squeeze(array)
    if array.ndim == 3 and array.shape[0] in (1, 3, 4) and array.shape[-1] not in (1, 3, 4):
        array = np.moveaxis(array, 0, -1)
    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=2)
    if array.ndim != 3:
        raise ValueError(f"Unsupported fundus image shape: {array.shape}")
    array = array[..., :3]
    if array.dtype != np.uint8:
        array = np.nan_to_num(array.astype(np.float32), nan=0.0, posinf=255.0, neginf=0.0)
        minimum = float(array.min()) if array.size else 0.0
        maximum = float(array.max()) if array.size else 0.0
        if maximum <= 1.0 and minimum >= 0.0:
            array *= 255.0
        elif maximum > 255.0 or minimum < 0.0:
            array = (array - minimum) / max(maximum - minimum, 1e-6) * 255.0
        array = np.clip(array, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(array)


def preprocess_clip_dr(image) -> torch.Tensor:
    """Official CLIP-DR evaluation transform: resize 256, center-crop 224, normalize."""
    rgb = _to_rgb_uint8(image)
    pil_image = Image.fromarray(rgb)
    pil_image = pil_image.resize((256, 256), Image.Resampling.BILINEAR)
    left = (256 - 224) // 2
    pil_image = pil_image.crop((left, left, left + 224, left + 224))
    normalized = np.asarray(pil_image, dtype=np.float32) / 255.0
    normalized = (normalized - IMAGENET_MEAN) / IMAGENET_STD
    return torch.from_numpy(np.moveaxis(normalized, -1, 0)).contiguous()


class CLIPDRPreprocessd(MapTransform):
    def __call__(self, data):
        result = dict(data)
        for key in self.keys:
            result[key] = preprocess_clip_dr(result[key])
        return result


class TextEncoder(nn.Module):
    def __init__(self, clip_model):
        super().__init__()
        self.transformer = clip_model.transformer
        self.positional_embedding = clip_model.positional_embedding
        self.ln_final = clip_model.ln_final
        self.text_projection = clip_model.text_projection

    def forward(self, prompts, tokenized_prompts):
        values = prompts.type(self.dtype) + self.positional_embedding.type(self.dtype)
        values = self.transformer(values.permute(1, 0, 2)).permute(1, 0, 2)
        values = self.ln_final(values).type(self.dtype)
        return values[
            torch.arange(values.shape[0], device=values.device),
            tokenized_prompts.argmax(dim=-1),
        ] @ self.text_projection

    @property
    def dtype(self):
        return self.transformer.resblocks[0].mlp.c_fc.weight.dtype


class PlainPromptLearner(nn.Module):
    def __init__(self, clip_model, num_ranks=5, num_context_tokens=10):
        super().__init__()
        dtype = clip_model.token_embedding.weight.dtype
        embedding_dim = clip_model.token_embedding.embedding_dim
        self.num_ranks = num_ranks
        self.num_context_tokens = num_context_tokens
        self.context_embeds = nn.Parameter(torch.empty(num_context_tokens, embedding_dim, dtype=dtype))
        self.rank_embeds = nn.Parameter(torch.empty(num_ranks, 1, embedding_dim, dtype=dtype))
        nn.init.normal_(self.context_embeds, std=0.02)
        nn.init.normal_(self.rank_embeds, std=0.02)

        sentence_length = 1 + num_context_tokens + 1 + 1 + 1
        pseudo_tokens = torch.zeros(num_ranks, 77, dtype=torch.long)
        pseudo_tokens[:, :sentence_length] = torch.arange(sentence_length, dtype=torch.long)
        self.register_buffer("psudo_sentence_tokens", pseudo_tokens, persistent=False)

        with torch.no_grad():
            null_embed = clip_model.token_embedding(torch.tensor([0]))[0]
            sot_embed = clip_model.token_embedding(torch.tensor([49406]))[0]
            eot_embed = clip_model.token_embedding(torch.tensor([49407]))[0]
            full_stop_embed = clip_model.token_embedding(torch.tensor([269]))[0]
        sentence_embeds = null_embed[None, None].repeat(num_ranks, 77, 1)
        eot_positions = pseudo_tokens.argmax(dim=-1)
        rank_indices = torch.arange(num_ranks)
        sentence_embeds[:, 0, :] = sot_embed
        sentence_embeds[rank_indices, eot_positions] = eot_embed
        sentence_embeds[rank_indices, eot_positions - 1] = full_stop_embed
        self.register_buffer("sentence_embeds", sentence_embeds, persistent=False)

    def forward(self):
        context = self.context_embeds[None].expand(self.num_ranks, -1, -1)
        sentence = self.sentence_embeds.clone()
        sentence[:, 1 : 1 + self.num_context_tokens + 1] = torch.cat(
            [context, self.rank_embeds], dim=1
        )
        return sentence


class CLIPDRModel(nn.Module):
    def __init__(self, clip_model):
        super().__init__()
        clip_model.float()
        self.image_encoder = clip_model.visual
        self.text_encoder = TextEncoder(clip_model)
        self.prompt_learner = PlainPromptLearner(clip_model)
        self.psudo_sentence_tokens = self.prompt_learner.psudo_sentence_tokens
        self.logit_scale = clip_model.logit_scale

    def forward(self, images):
        sentence_embeds = self.prompt_learner()
        text_features = self.text_encoder(sentence_embeds, self.psudo_sentence_tokens)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        image_features = self.image_encoder(images)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        return self.logit_scale.exp() * image_features @ text_features.t()


class CLIPDRClassification(BasicInferTask):
    def __init__(
        self,
        path,
        network=None,
        type=InferType.CLASSIFICATION,
        labels=None,
        dimension=2,
        description="CLIP-DR ranking-aware diabetic retinopathy classification",
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
        self.checkpoint_path = os.environ.get(
            "CLIP_DR_CHECKPOINT_PATH", "/opt/monai/models/clip-dr/APTOS.ckpt"
        )
        self.expected_sha256 = os.environ.get("CLIP_DR_CHECKPOINT_SHA256", "").strip().lower()
        self.temperature = float(os.environ.get("CLIP_DR_TEMPERATURE", "1.0"))
        self.calibration_status = os.environ.get(
            "CLIP_DR_CALIBRATION_STATUS", "not_locally_calibrated"
        )
        self._model = None
        self._checkpoint_sha256 = None

    def is_valid(self) -> bool:
        return True

    def pre_transforms(self, data=None) -> Sequence[Callable]:
        return [LoadImaged(keys="image"), CLIPDRPreprocessd(keys="image")]

    def inferer(self, data=None) -> Inferer:
        return SimpleInferer()

    def _load_model(self, device):
        if self._model is None:
            checkpoint = Path(self.checkpoint_path)
            if not checkpoint.is_file():
                raise FileNotFoundError("checkpoint CLIP-DR APTOS non installé")
            actual_sha256 = sha256_file(str(checkpoint))
            if not self.expected_sha256:
                raise RuntimeError("CLIP_DR_CHECKPOINT_SHA256 is required")
            if actual_sha256 != self.expected_sha256:
                raise RuntimeError("CLIP-DR checkpoint SHA-256 mismatch")
            if self.temperature <= 0:
                raise ValueError("CLIP_DR_TEMPERATURE must be greater than zero")

            import clip

            base_model, _ = clip.load("RN50", device="cpu", jit=False)
            model = CLIPDRModel(base_model)
            checkpoint_data = torch.load(str(checkpoint), map_location="cpu")
            state_dict = checkpoint_data.get("state_dict", checkpoint_data)
            # Lightning stores the CLIP-DR network under ``module`` and also
            # serializes training-only FDS statistics.  Only the official
            # network namespace is valid for inference; it is still loaded
            # strictly after removing that wrapper prefix.
            state_dict = {
                key.removeprefix("module."): value
                for key, value in state_dict.items()
                if key.startswith("module.")
            }
            if not state_dict:
                raise RuntimeError("CLIP-DR checkpoint contains no module state")
            model.load_state_dict(state_dict, strict=True)
            model.eval()
            self._model = model
            self._checkpoint_sha256 = actual_sha256
        self._model.to(torch.device(device))
        return self._model

    def _get_network(self, device, data):
        return self._load_model(device)

    def run_inferer(self, data, convert_to_batch=True, device="cpu"):
        started = time.perf_counter()
        network = self._get_network("cpu", data)
        inputs = data[self.input_key]
        inputs = inputs if torch.is_tensor(inputs) else torch.as_tensor(inputs)
        inputs = inputs.unsqueeze(0) if convert_to_batch else inputs
        with torch.inference_mode():
            logits = network(inputs.to("cpu")) / self.temperature
            probabilities = F.softmax(logits, dim=1)

        grade_index = int(probabilities.argmax(dim=1)[0])
        confidence = float(probabilities[0, grade_index])
        all_probabilities = {
            CLIP_DR_CLASSES[index]: float(probabilities[0, index]) for index in range(5)
        }
        # MONAI Label's classification writer expects the ``array`` property
        # provided by MetaTensor, including for JSON-only analyze requests.
        data[self.output_label_key] = MetaTensor(probabilities[0].cpu())
        data[self.output_json_key] = {
            "dr_grade": grade_index,
            "dr_label": CLIP_DR_CLASSES[grade_index],
            "dr_probability": confidence,
            "dr_all_probabilities": all_probabilities,
            "status": "ok",
            "model_id": "Qinkaiyu/CLIP-DR",
            "model_commit": OFFICIAL_COMMIT,
            "checkpoint_name": Path(self.checkpoint_path).name,
            "checkpoint_sha256": self._checkpoint_sha256,
            "calibration_status": self.calibration_status,
            "temperature": self.temperature,
            "preprocessing_version": "clip-dr-official-256-center224-v1",
            "inference_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "device": "cpu",
        }
        return data

    def run_invert_transforms(self, data, pre_transforms, transforms):
        return data

    def post_transforms(self, data=None) -> Sequence[Callable]:
        return []
