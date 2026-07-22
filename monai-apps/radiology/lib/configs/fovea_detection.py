import logging
import os
import hashlib
from typing import Any, Dict, Optional, Union

import lib.infers
from monailabel.interfaces.config import TaskConfig
from monailabel.interfaces.tasks.infer_v2 import InferTask
from monailabel.interfaces.tasks.scoring import ScoringMethod
from monailabel.interfaces.tasks.strategy import Strategy
from monailabel.interfaces.tasks.train import TrainTask

logger = logging.getLogger(__name__)
MODEL_SHA256 = "114daf518186122cdbbae66fceeb3fd00f6411b72b99bdc81c1272e36441055a"


class FoveaDetection(TaskConfig):
    def init(self, name: str, model_dir: str, conf: Dict[str, str], planner: Any, **kwargs):
        super().init(name, model_dir, conf, planner, **kwargs)
        self.labels = {}
        self.path = os.environ.get(
            "VASCX_FOVEA_MODEL_PATH",
            "/opt/monai/models/vascx/fovea/fovea_may26.pt",
        )
        if not os.path.isfile(self.path):
            logger.error(
                "VascX fovea model is unavailable at %s; run tools/setup_vascx_fovea.sh",
                self.path,
            )
        else:
            digest = hashlib.sha256()
            with open(self.path, "rb") as model_file:
                for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != MODEL_SHA256:
                logger.error(
                    "VascX fovea model checksum mismatch at %s; expected %s, got %s",
                    self.path,
                    MODEL_SHA256,
                    digest.hexdigest(),
                )
            else:
                logger.info("VascX fovea model checksum verified: %s", self.path)

    def infer(self) -> InferTask:
        return lib.infers.FoveaDetection(model_path=self.path)

    def trainer(self) -> Optional[TrainTask]:
        return None

    def strategy(self) -> Union[None, Strategy, Dict[str, Strategy]]:
        return None

    def scoring_method(self) -> Union[None, ScoringMethod, Dict[str, ScoringMethod]]:
        return None
