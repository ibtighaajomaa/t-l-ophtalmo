import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from lib.infers.composite_segmenter import CompositeSegmenter
from lib.infers.fovea_detection import _get_model, detect_fovea_rgb, loaded_image_to_rgb


class FakeModel:
    def predict_preprocessed(self, data, num_workers, batch_size):
        assert Path(data[0]["image"]).exists()
        assert num_workers == 0
        assert batch_size == 1
        return pd.DataFrame([[60.0, 25.0]], columns=["x0", "y0"])


@pytest.mark.parametrize(
    "image,expected_shape",
    [
        (np.zeros((50, 100), dtype=np.uint8), (50, 100, 3)),
        (np.zeros((1, 50, 100), dtype=np.uint8), (50, 100, 3)),
        (np.zeros((3, 50, 100), dtype=np.uint8), (50, 100, 3)),
        (np.zeros((50, 100, 3), dtype=np.uint8), (50, 100, 3)),
    ],
)
def test_loaded_image_to_rgb_handles_supported_shapes(image, expected_shape):
    assert loaded_image_to_rgb(image).shape == expected_shape


@patch("lib.infers.fovea_detection._get_model", return_value=FakeModel())
@patch("lib.infers.fovea_detection.restore_fovea_coordinates", side_effect=lambda x, y, bounds: (x, y))
@patch("lib.infers.fovea_detection.preprocess_fundus_rgb", side_effect=lambda image: (image, {}))
def test_detect_fovea_returns_source_and_normalized_coordinates(_preprocess, _restore, _get_model, tmp_path):
    model_path = tmp_path / "fovea.pt"
    model_path.touch()
    result = detect_fovea_rgb(
        np.zeros((50, 100, 3), dtype=np.uint8),
        str(model_path),
        "cpu",
    )
    assert result["x_px"] == 60.0
    assert result["y_px"] == 25.0
    assert result["x_normalized"] == 0.6
    assert result["y_normalized"] == 0.5
    assert result["source_width"] == 100
    assert result["source_height"] == 50


@patch("lib.infers.fovea_detection._get_model", return_value=FakeModel())
@patch("lib.infers.fovea_detection.restore_fovea_coordinates", side_effect=lambda x, y, bounds: (x, y))
@patch("lib.infers.fovea_detection.preprocess_fundus_rgb", side_effect=lambda image: (image, {}))
def test_detect_fovea_rejects_out_of_bounds_result(_preprocess, _restore, _get_model, tmp_path):
    class OutOfBoundsModel(FakeModel):
        def predict_preprocessed(self, data, num_workers, batch_size):
            return pd.DataFrame([[101.0, 10.0]], columns=["x0", "y0"])

    _get_model.return_value = OutOfBoundsModel()
    with pytest.raises(ValueError, match="outside"):
        detect_fovea_rgb(np.zeros((50, 100, 3), dtype=np.uint8), str(tmp_path / "fovea.pt"), "cpu")


def test_missing_model_is_reported_clearly(tmp_path):
    with pytest.raises(FileNotFoundError, match="VascX fovea model not found"):
        _get_model(str(tmp_path / "missing.pt"), __import__("torch").device("cpu"))


def test_composite_overlay_draws_yellow_fovea_marker():
    task = CompositeSegmenter.__new__(CompositeSegmenter)
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    overlay = task._create_overlay(
        image,
        odoc_pred=None,
        lesion_pred=None,
        vessel_mask=None,
        fovea={"x_px": 50.0, "y_px": 50.0},
    )
    assert np.array_equal(overlay[50, 50], np.array([255, 230, 0], dtype=np.uint8))
