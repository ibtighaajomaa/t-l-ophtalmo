import os
from typing import Any, Dict, Optional, Union

import lib.infers
from monailabel.interfaces.config import TaskConfig
from monailabel.interfaces.tasks.infer_v2 import InferTask
from monailabel.interfaces.tasks.scoring import ScoringMethod
from monailabel.interfaces.tasks.strategy import Strategy
from monailabel.interfaces.tasks.train import TrainTask


class Dino2DRClassification(TaskConfig):
    def init(self, name: str, model_dir: str, conf: Dict[str, str], planner: Any, **kwargs):
        super().init(name, model_dir, conf, planner, **kwargs)
        self.labels = {
            "no_dr": 0,
            "mild_npdr": 1,
            "moderate_npdr": 2,
            "severe_npdr": 3,
            "proliferative_dr": 4,
        }
        self.path = [
            os.environ.get(
                "DINO2_DR_CHECKPOINT_PATH",
                "/opt/monai/models/dino2-dr/dino2_dr_fsmt.pth",
            )
        ]

    def infer(self) -> Union[InferTask, Dict[str, InferTask]]:
        return lib.infers.Dino2DRClassification(
            path=self.path, network=None, labels=self.labels, preload=False
        )

    def trainer(self) -> Optional[TrainTask]:
        return None

    def strategy(self) -> Union[None, Strategy, Dict[str, Strategy]]:
        return None

    def scoring_method(self) -> Union[None, ScoringMethod, Dict[str, ScoringMethod]]:
        return None
