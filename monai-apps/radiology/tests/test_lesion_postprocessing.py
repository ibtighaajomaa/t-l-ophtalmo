from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "lib" / "infers" / "lesion_seg.py"


def _load_function_source():
    source = MODULE_PATH.read_text()
    start = source.index("def suppress_optic_disc_lesions")
    end = source.index("\n\n\nclass CaptureOriginalSpatialShaped", start)
    namespace = {"np": np, "cv2": __import__("cv2"), "logger": __import__("logging").getLogger(__name__)}
    exec(source[start:end], namespace)
    return namespace["suppress_optic_disc_lesions"]


def _load_macular_function():
    source = MODULE_PATH.read_text()
    start = source.index("def suppress_macular_zone_lesions")
    end = source.index("\n\n\nclass CaptureOriginalSpatialShaped", start)
    namespace = {
        "np": np,
        "cv2": __import__("cv2"),
        "logger": __import__("logging").getLogger(__name__),
    }
    exec(source[start:end], namespace)
    return namespace["suppress_macular_zone_lesions"]


def test_suppresses_only_lesions_near_optic_disc():
    suppress = _load_function_source()
    lesions = np.zeros((100, 100), dtype=np.uint8)
    lesions[45:55, 45:55] = 1
    lesions[10:14, 80:84] = 2
    odoc = np.zeros_like(lesions)
    odoc[47:53, 47:53] = 1

    result = suppress(lesions, odoc, margin_ratio=0.02)

    assert not result[45:55, 45:55].any()
    assert np.all(result[10:14, 80:84] == 2)


def test_resizes_optic_disc_mask_before_suppression():
    suppress = _load_function_source()
    lesions = np.zeros((20, 40), dtype=np.uint8)
    lesions[8:12, 18:22] = 3
    odoc = np.zeros((10, 20), dtype=np.uint8)
    odoc[4:6, 9:11] = 2

    result = suppress(lesions, odoc, margin_ratio=0)

    assert not result[8:12, 18:22].any()


def test_suppresses_macular_zone_but_preserves_peripheral_lesions():
    suppress = _load_macular_function()
    lesions = np.zeros((100, 100), dtype=np.uint8)
    lesions[47:53, 47:53] = 1
    lesions[15:20, 75:80] = 2

    result = suppress(lesions, radius_ratio=0.08)

    assert not result[47:53, 47:53].any()
    assert np.all(result[15:20, 75:80] == 2)


def test_removes_whole_component_crossing_macular_boundary():
    suppress = _load_macular_function()
    lesions = np.zeros((100, 100), dtype=np.uint8)
    lesions[45:55, 45:70] = 1

    result = suppress(lesions, radius_ratio=0.05)

    assert not result.any()
