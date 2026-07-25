import os
from typing import Any, Dict, Optional, Union

import lib.infers
from monailabel.interfaces.config import TaskConfig
from monailabel.interfaces.tasks.infer_v2 import InferTask
from monailabel.interfaces.tasks.scoring import ScoringMethod
from monailabel.interfaces.tasks.strategy import Strategy
from monailabel.interfaces.tasks.train import TrainTask


class NeovascularizationSeg(TaskConfig):
    def init(self, name: str, model_dir: str, conf: Dict[str, str], planner: Any, **kwargs):
        super().init(name, model_dir, conf, planner, **kwargs)
        self.labels = {"Neovascularisation": 1}
        self.path = os.environ.get(
            "BIGEYE_SEG_MODEL_PATH",
            os.path.join(self.model_dir, "deeplab_lesion_segmentation.hdf5"),
        )

    def infer(self) -> Union[InferTask, Dict[str, InferTask]]:
        return lib.infers.NeovascularizationSeg(path=self.path, labels=self.labels)

    def trainer(self) -> Optional[TrainTask]:
        return None

    def strategy(self) -> Union[None, Strategy, Dict[str, Strategy]]:
        return None

    def scoring_method(self) -> Union[None, ScoringMethod, Dict[str, ScoringMethod]]:
        return None
