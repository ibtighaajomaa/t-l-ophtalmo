import os
from typing import Any, Dict, Optional, Union

import lib.infers
from monailabel.interfaces.config import TaskConfig
from monailabel.interfaces.tasks.infer_v2 import InferTask
from monailabel.interfaces.tasks.scoring import ScoringMethod
from monailabel.interfaces.tasks.strategy import Strategy
from monailabel.interfaces.tasks.train import TrainTask


class FlairDRClassification(TaskConfig):
    def init(self, name: str, model_dir: str, conf: Dict[str, str], planner: Any, **kwargs):
        super().init(name, model_dir, conf, planner, **kwargs)
        self.labels = {
            "no_dr": 0,
            "mild_npdr": 1,
            "moderate_npdr": 2,
            "severe_npdr": 3,
            "proliferative_dr": 4,
        }
        # PyTorchModelHubMixin resolves this repository through the persistent HF cache.
        self.path = [os.environ.get("FLAIR_MODEL_ID", "jusiro2/FLAIR")]

    def infer(self) -> Union[InferTask, Dict[str, InferTask]]:
        return lib.infers.FlairDRClassification(
            path=self.path,
            network=None,
            labels=self.labels,
            preload=False,
        )

    def trainer(self) -> Optional[TrainTask]:
        return None

    def strategy(self) -> Union[None, Strategy, Dict[str, Strategy]]:
        return None

    def scoring_method(self) -> Union[None, ScoringMethod, Dict[str, ScoringMethod]]:
        return None
