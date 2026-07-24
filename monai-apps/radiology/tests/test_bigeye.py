import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from lib.infers.bigeye import (  # noqa: E402
    BIGEYE_COMMIT,
    BIGEYE_MODEL_ID,
    BIGEYE_SHA256,
    LESION_NAMES,
    find_model_path,
    model_metadata,
    predict_bigeye,
    preprocess_bigeye_image,
    quantify_lesion_mask,
    verify_model_file,
)


def _reference_preprocess(rgb):
    bgr = np.ascontiguousarray(rgb[..., ::-1])
    bgr = cv2.resize(bgr, (512, 512), interpolation=cv2.INTER_LINEAR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    channels = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab = cv2.merge((clahe.apply(channels[0]), channels[1], channels[2]))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR).astype(np.float32) / 255.0


def test_class_mapping_contains_six_distinct_lesions():
    assert LESION_NAMES == {
        1: "microaneurysms",
        2: "hard_exudates",
        3: "cotton_wool_spots",
        4: "hemorrhages",
        5: "neovascularization",
        6: "laser_scars",
    }


def test_preprocess_matches_bigeye_opencv_pipeline():
    rows = np.arange(24, dtype=np.uint8)[:, None]
    cols = np.arange(32, dtype=np.uint8)[None, :]
    rgb = np.stack(
        (
            np.broadcast_to(rows * 7, (24, 32)),
            np.broadcast_to(cols * 5, (24, 32)),
            (rows * 3 + cols * 2).astype(np.uint8),
        ),
        axis=-1,
    )
    actual = preprocess_bigeye_image(np.transpose(rgb, (2, 0, 1)))
    expected = _reference_preprocess(rgb)
    assert actual.shape == (1, 512, 512, 3)
    np.testing.assert_array_equal(actual[0], expected)


def test_predict_maps_all_seven_softmax_channels():
    class FakeModel:
        def predict(self, inputs, verbose=0):
            assert inputs.shape == (1, 512, 512, 3)
            output = np.zeros((1, 512, 512, 7), dtype=np.float32)
            for class_id in range(7):
                output[0, class_id, :, class_id] = 1.0
            return output

    image = np.zeros((3, 16, 16), dtype=np.uint8)
    prediction = predict_bigeye(FakeModel(), image)
    for class_id in range(7):
        assert np.all(prediction[class_id] == class_id)


def test_checkpoint_hash_failure_is_explicit(tmp_path):
    checkpoint = tmp_path / "bad.hdf5"
    checkpoint.write_bytes(b"not-bigeye")
    with pytest.raises(ValueError, match="Invalid BigEye checkpoint SHA-256"):
        verify_model_file(str(checkpoint))


def test_missing_checkpoint_is_explicit(tmp_path):
    with pytest.raises(FileNotFoundError, match="setup_bigeye.sh"):
        find_model_path([str(tmp_path / "missing.hdf5")])


def test_model_metadata_is_traceable():
    assert model_metadata() == {
        "model_id": BIGEYE_MODEL_ID,
        "model_commit": BIGEYE_COMMIT,
        "checkpoint_sha256": BIGEYE_SHA256,
    }


def test_quantification_counts_eight_connected_components_and_pixels():
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[1, 1] = 1
    mask[3:5, 3:5] = 1
    mask[7:9, 2:4] = 2
    mask[10:12, 2:4] = 3
    mask[2:4, 12:14] = 4
    mask[8:10, 12:14] = 5
    mask[14:16, 12:14] = 6

    result = quantify_lesion_mask(mask)

    assert result["microaneurysms"] == 2
    assert result["hard_exudates"] == 1
    assert result["cotton_wool_spots"] == 1
    assert result["hemorrhages"] == 1
    assert result["neovascularization"] == 1
    assert result["laser_scars"] == 1
    assert result["exudates"] == 2
    assert result["pixel_counts"]["microaneurysms"] == 5


@pytest.mark.skipif(
    not os.environ.get("BIGEYE_MODEL_PATH"),
    reason="Set BIGEYE_MODEL_PATH to run the real checkpoint compatibility test",
)
def test_real_checkpoint_loads_with_expected_shapes():
    from lib.infers.bigeye import load_bigeye_model

    model = load_bigeye_model(os.environ["BIGEYE_MODEL_PATH"])
    assert tuple(model.input_shape) == (None, 512, 512, 3)
    assert tuple(model.output_shape) == (None, 512, 512, 7)
