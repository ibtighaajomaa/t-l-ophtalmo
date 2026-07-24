import sys
import types
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "monailabel" not in sys.modules:
    monailabel = types.ModuleType("monailabel")
    infer_v2 = types.ModuleType("monailabel.interfaces.tasks.infer_v2")
    infer_v2.InferType = types.SimpleNamespace(CLASSIFICATION="classification")
    basic_infer = types.ModuleType("monailabel.tasks.infer.basic_infer")
    basic_infer.BasicInferTask = object
    sys.modules.update({
        "monailabel": monailabel,
        "monailabel.interfaces": types.ModuleType("monailabel.interfaces"),
        "monailabel.interfaces.tasks": types.ModuleType("monailabel.interfaces.tasks"),
        "monailabel.interfaces.tasks.infer_v2": infer_v2,
        "monailabel.tasks": types.ModuleType("monailabel.tasks"),
        "monailabel.tasks.infer": types.ModuleType("monailabel.tasks.infer"),
        "monailabel.tasks.infer.basic_infer": basic_infer,
    })

from lib.infers.dino2_dr_classification import Dino2DRModel, preprocess_dino2_dr


def test_official_preprocessing_shape_and_finite_values():
    image = np.zeros((720, 960, 3), dtype=np.uint8)
    cv2.circle(image, (480, 360), 310, (160, 100, 70), -1)
    tensor = preprocess_dino2_dr(image)
    assert tensor.shape == (3, 504, 504)
    assert tensor.dtype == torch.float32
    assert torch.isfinite(tensor).all()


def test_exact_classifier_head_shape():
    class Backbone(torch.nn.Module):
        def forward(self, inputs):
            return torch.zeros((inputs.shape[0], 1536))

    model = Dino2DRModel(Backbone())
    assert model.classifier[0].in_features == 1536
    assert model.classifier[0].out_features == 512
    assert model.classifier[2].p == pytest.approx(0.3)
    assert model.classifier[3].out_features == 5
    assert model(torch.zeros((2, 3, 504, 504))).shape == (2, 5)
