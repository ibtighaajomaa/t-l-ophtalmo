"""CPU-only inference wrapper for the bundled FTHNet4 model."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from io import BytesIO
from pathlib import Path

import numpy as np
import pydicom
import torch
import torch.nn.functional as F
from PIL import Image
from pydicom.pixel_data_handlers.util import apply_voi_lut
from torchvision import transforms


MODEL_ROOT = (
    Path(__file__).resolve().parent.parent
    / "QualiteOpht"
    / "UserschiheAppDataLocalTempBasiQA"
)
DEFAULT_CHECKPOINT = MODEL_ROOT / "pretrained_weight" / "net_g_226264S4.pth"


class FTHNetCPU:
    def __init__(self, checkpoint_path: str | os.PathLike | None = None):
        torch.set_num_threads(int(os.environ.get("FTHNET_CPU_THREADS", "4")))
        self.device = torch.device("cpu")
        self.model = self._build_model()

        checkpoint_file = Path(
            checkpoint_path or os.environ.get("FTHNET_CHECKPOINT", DEFAULT_CHECKPOINT)
        )
        if not checkpoint_file.is_file():
            raise FileNotFoundError(f"FTHNet checkpoint not found: {checkpoint_file}")

        checkpoint = torch.load(
            checkpoint_file, map_location=self.device, weights_only=True
        )
        state = checkpoint.get("params_ema") or checkpoint.get("params") or checkpoint
        self.model.load_state_dict(state, strict=True)
        self.model.eval()

        self.transform = transforms.Compose(
            [
                transforms.Resize((512, 512)),
                transforms.CenterCrop(384),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=(0.485, 0.456, 0.406),
                    std=(0.229, 0.224, 0.225),
                ),
            ]
        )

    @staticmethod
    def _build_model():
        # The upstream repository uses top-level imports such as
        # ``utils.registry``. Add its package root without modifying the
        # application's global working directory.
        basiqa_root = MODEL_ROOT / "basiqa"
        root_text = str(basiqa_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)

        # FTHNet only needs the registry decorator from the upstream utilities.
        # Avoid importing the entire research utility package (pandas/OpenCV,
        # training helpers) in the lightweight inference worker.
        if "utils.registry" not in sys.modules:
            registry_module = types.ModuleType("utils.registry")

            class _Registry:
                def register(self):
                    return lambda cls: cls

            registry_module.ARCH_REGISTRY = _Registry()
            utils_module = types.ModuleType("utils")
            utils_module.__path__ = []
            sys.modules["utils"] = utils_module
            sys.modules["utils.registry"] = registry_module

        architecture_file = basiqa_root / "archs" / "fthnet4_arch.py"
        spec = importlib.util.spec_from_file_location(
            "basiqa_fthnet4_cpu", architecture_file
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot import FTHNet architecture: {architecture_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module.FTHNet4(
            ffa_out_ch=32,
            tn_in_ch=384,
            hyper_in_ch=384,
            embed_dim=64,
            depths=[2, 2, 6, 2],
            num_heads=[2, 4, 8, 16],
            window_size=12,
            drop_rate=0.0,
            attn_drop_rate=0.0,
            drop_path_rate=0.1,
        )

    @staticmethod
    def _target_forward(parameters):
        x = parameters["target_in_vec"]
        for index in range(1, 6):
            weight = parameters[f"target_fc{index}w"]
            bias = parameters[f"target_fc{index}b"]
            batch = x.shape[0]
            x = F.conv2d(
                x.reshape(1, batch * x.shape[1], x.shape[2], x.shape[3]),
                weight.reshape(
                    batch * weight.shape[1],
                    weight.shape[2],
                    weight.shape[3],
                    weight.shape[4],
                ),
                bias.reshape(-1),
                groups=batch,
            ).reshape(batch, weight.shape[1], x.shape[2], x.shape[3])
            if index < 5:
                x = torch.sigmoid(x)
        return x.squeeze()

    def predict(self, image: Image.Image) -> dict[str, float | str]:
        tensor = self.transform(image.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            parameters = self.model(tensor)
            normalized_score = float(self._target_forward(parameters).item())

        normalized_score = max(0.0, min(1.0, normalized_score))
        score = round(normalized_score * 100.0, 2)
        good_threshold = float(os.environ.get("FTHNET_GOOD_THRESHOLD", "70"))
        acceptable_threshold = float(
            os.environ.get("FTHNET_ACCEPTABLE_THRESHOLD", "40")
        )
        if score >= good_threshold:
            category = "good"
            label = "Bonne qualité"
        elif score >= acceptable_threshold:
            category = "acceptable"
            label = "Qualité acceptable"
        else:
            category = "bad"
            label = "Qualité mauvaise"
        return {"score": score, "category": category, "label": label}

    def predict_file(self, image_path: str | os.PathLike):
        image_path = Path(image_path)
        if image_path.suffix.lower() in {".dcm", ".dicom"}:
            image, metadata = self.read_dicom(image_path)
            result = self.predict(image)
            result.update(metadata)
            return result
        with Image.open(image_path) as image:
            return self.predict(image)

    @staticmethod
    def read_dicom(image_path: str | os.PathLike):
        dataset = pydicom.dcmread(image_path)
        modality = str(dataset.get("Modality", "")).upper()
        if modality != "OP":
            raise ValueError(
                f"Unsupported DICOM modality {modality or '(missing)'}; expected OP"
            )

        pixels = dataset.pixel_array
        if pixels.ndim == 4:
            pixels = pixels[0]
        elif pixels.ndim == 3 and pixels.shape[-1] not in (3, 4):
            pixels = pixels[0]

        if pixels.ndim == 2:
            try:
                pixels = apply_voi_lut(pixels, dataset)
            except Exception:
                pass
            pixels = np.asarray(pixels, dtype=np.float32)
            low, high = np.percentile(pixels, (1, 99))
            if high <= low:
                low, high = float(pixels.min()), float(pixels.max())
            pixels = np.clip((pixels - low) / max(high - low, 1e-6), 0, 1)
            if str(dataset.get("PhotometricInterpretation", "")) == "MONOCHROME1":
                pixels = 1.0 - pixels
            pixels = (pixels * 255).astype(np.uint8)
            image = Image.fromarray(pixels, mode="L").convert("RGB")
        else:
            pixels = np.asarray(pixels)
            if pixels.dtype != np.uint8:
                pixels = pixels.astype(np.float32)
                low, high = np.percentile(pixels, (1, 99))
                pixels = np.clip(
                    (pixels - low) / max(high - low, 1e-6), 0, 1
                )
                pixels = (pixels * 255).astype(np.uint8)
            image = Image.fromarray(pixels[..., :3]).convert("RGB")

        metadata = {
            "modality": modality,
            "study_instance_uid": str(dataset.get("StudyInstanceUID", "")),
            "series_instance_uid": str(dataset.get("SeriesInstanceUID", "")),
            "sop_instance_uid": str(dataset.get("SOPInstanceUID", "")),
            "patient_id": str(dataset.get("PatientID", "")),
        }
        return image, metadata

    def predict_orthanc_instance(self, instance_id: str, orthanc_url: str):
        import requests

        base = orthanc_url.rstrip("/")
        tags_response = requests.get(
            f"{base}/instances/{instance_id}/simplified-tags", timeout=30
        )
        tags_response.raise_for_status()
        tags = tags_response.json()
        modality = str(tags.get("Modality", "")).upper()
        if modality != "OP":
            raise ValueError(
                f"Orthanc instance {instance_id} has modality "
                f"{modality or '(missing)'}, expected OP"
            )

        image_response = requests.get(
            f"{base}/instances/{instance_id}/rendered",
            headers={"Accept": "image/png"},
            timeout=60,
        )
        image_response.raise_for_status()
        with Image.open(BytesIO(image_response.content)) as image:
            result = self.predict(image)
        result.update(
            {
                "orthanc_instance_id": instance_id,
                "modality": modality,
                "study_instance_uid": tags.get("StudyInstanceUID", ""),
                "series_instance_uid": tags.get("SeriesInstanceUID", ""),
                "sop_instance_uid": tags.get("SOPInstanceUID", ""),
                "patient_id": tags.get("PatientID", ""),
            }
        )
        return result
