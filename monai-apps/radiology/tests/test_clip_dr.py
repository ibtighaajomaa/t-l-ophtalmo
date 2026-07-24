import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from monai.data import MetaTensor

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from lib.infers.clip_dr_classification import (  # noqa: E402
    CLIPDRClassification,
    preprocess_clip_dr,
    sha256_file,
)


def test_preprocess_clip_dr_produces_expected_tensor():
    image = np.zeros((480, 720, 3), dtype=np.uint8)
    image[60:420, 90:630] = (120, 80, 40)

    result = preprocess_clip_dr(image)

    assert result.shape == (3, 224, 224)
    assert result.dtype == torch.float32
    assert torch.isfinite(result).all()


def test_preprocess_clip_dr_is_deterministic():
    image = np.arange(300 * 400 * 3, dtype=np.uint8).reshape(300, 400, 3)
    assert torch.equal(preprocess_clip_dr(image), preprocess_clip_dr(image))


def test_sha256_file(tmp_path):
    checkpoint = tmp_path / "APTOS.ckpt"
    checkpoint.write_bytes(b"clip-dr")
    assert sha256_file(str(checkpoint)) == hashlib.sha256(b"clip-dr").hexdigest()


def test_missing_checkpoint_fails_without_loading_clip(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIP_DR_CHECKPOINT_PATH", str(tmp_path / "missing.ckpt"))
    task = CLIPDRClassification(path=[], network=None, labels={})

    with pytest.raises(FileNotFoundError, match="non installé"):
        task._load_model("cpu")


def test_run_inferer_emits_checkpoint_metadata(monkeypatch):
    task = CLIPDRClassification(path=[], network=None, labels={})
    monkeypatch.setattr(task, "_get_network", lambda device, data: torch.nn.Identity())
    task.checkpoint_path = "/models/clip-dr/APTOS.ckpt"
    task._checkpoint_sha256 = "test-sha"

    result = task.run_inferer({"image": torch.arange(5, dtype=torch.float32)})
    metadata = result[task.output_json_key]

    assert metadata["checkpoint_name"] == "APTOS.ckpt"
    assert metadata["checkpoint_sha256"] == "test-sha"
    assert metadata["status"] == "ok"
    assert isinstance(result[task.output_label_key], MetaTensor)
