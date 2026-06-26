import logging
import os
from typing import Any, Dict, Optional, Union

import lib.infers
import segmentation_models_pytorch as smp
from monailabel.interfaces.config import TaskConfig
from monailabel.interfaces.tasks.infer_v2 import InferTask
from monailabel.interfaces.tasks.scoring import ScoringMethod
from monailabel.interfaces.tasks.strategy import Strategy
from monailabel.interfaces.tasks.train import TrainTask

logger = logging.getLogger(__name__)


class CompositeSeg(TaskConfig):
    def __init__(self):
        super().__init__()

    def init(self, name: str, model_dir: str, conf: Dict[str, str], planner: Any, **kwargs):
        super().init(name, model_dir, conf, planner, **kwargs)

        self.labels = {
            "optic_disc": 1,
            "optic_cup": 2,
            "microaneurysms": 1,
            "hemorrhages": 2,
            "hard_exudates": 3,
            "soft_exudates": 4,
            "vessel": 1,
        }

        self.lesion_path = [
            os.path.join(self.model_dir, "lesion_seg_ddr.pt"),
            os.path.join(self.model_dir, "lesion_seg.pt"),
        ]
        self.vessel_path = [
            os.path.join(self.model_dir, "vessel_seg.pt"),
        ]

        self.lesion_network = smp.DeepLabV3Plus(
            encoder_name="efficientnet-b3",
            in_channels=3,
            classes=5,
            encoder_weights=None,
        )
        self.vessel_network = smp.UnetPlusPlus(
            encoder_name="efficientnet-b3",
            in_channels=3,
            classes=1,
            encoder_weights=None,
        )

    def infer(self) -> Union[InferTask, Dict[str, InferTask]]:
        task: InferTask = lib.infers.CompositeSegmenter(
            lesion_model_path=self.lesion_path,
            vessel_model_path=self.vessel_path,
            lesion_network=self.lesion_network,
            vessel_network=self.vessel_network,
            lesion_labels={
                "microaneurysms": 1,
                "hemorrhages": 2,
                "hard_exudates": 3,
                "soft_exudates": 4,
            },
            vessel_labels={"vessel": 1},
            odoc_labels={"optic_disc": 1, "optic_cup": 2},
            preload=strtobool(self.conf.get("preload", "false")),
        )
        return task

    def trainer(self) -> Optional[TrainTask]:
        return None

    def strategy(self) -> Union[None, Strategy, Dict[str, Strategy]]:
        return None

    def scoring_method(self) -> Union[None, ScoringMethod, Dict[str, ScoringMethod]]:
        return None


def strtobool(val):
    return val.lower() in ("true", "1", "yes") if isinstance(val, str) else bool(val)
