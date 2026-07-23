import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.infers.deepseenet_plus import crop_center_square, crop_fovea_centered


def test_center_crop_landscape_uses_short_side():
    image = Image.fromarray(np.full((100, 200, 3), 255, dtype=np.uint8))
    cropped, geometry = crop_center_square(image)

    assert cropped.size == (100, 100)
    assert geometry["crop_box"] == {"left": 50, "top": 0, "right": 150, "bottom": 100}
    assert not any(geometry["padding"].values())


def test_fovea_crop_keeps_point_centered_and_pads_outside_source():
    image = Image.fromarray(np.full((100, 200, 3), 255, dtype=np.uint8))
    cropped, geometry = crop_fovea_centered(image, x_px=20, y_px=20)

    assert cropped.size == (100, 100)
    assert geometry["crop_box"] == {"left": -30, "top": -30, "right": 70, "bottom": 70}
    assert geometry["padding"] == {"left": 30, "top": 30, "right": 0, "bottom": 0}
    assert np.asarray(cropped)[0, 0].tolist() == [0, 0, 0]
    assert np.asarray(cropped)[50, 50].tolist() == [255, 255, 255]
