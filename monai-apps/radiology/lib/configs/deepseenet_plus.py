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
MODEL_SHA256 = {
    "drusen": "4db9beec22bc6023c7932bd4e329811225ae097f9d53d2589ed36409301cbe16",
    "pigment": "1b1aab356d0f643f231a94e55f273b088b83a6622cc06b057b1668f78004add0",
    "amd": "ad788e91c6f2ef803f49851017e9c3b9344d03ef68bb23161b560d3d33c75ae5",
}


class DeepSeeNetPlus(TaskConfig):
    def init(self, name: str, model_dir: str, conf: Dict[str, str], planner: Any, **kwargs):
        super().init(name, model_dir, conf, planner, **kwargs)
        self.labels = {}
        self.model_folder = os.environ.get("DEEPSEENET_MODEL_FOLDER", "/opt/monai/models/deepseenet-plus")
        missing = [
            risk_factor
            for risk_factor in ("drusen", "pigment", "amd")
            if not os.path.isfile(os.path.join(self.model_folder, f"{risk_factor}.h5"))
        ]
        if missing:
            logger.error("DeepSeeNet+ models unavailable in %s: %s", self.model_folder, ", ".join(missing))
        else:
            for risk_factor, expected in MODEL_SHA256.items():
                digest = hashlib.sha256()
                path = os.path.join(self.model_folder, f"{risk_factor}.h5")
                with open(path, "rb") as model_file:
                    for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                        digest.update(chunk)
                actual = digest.hexdigest()
                if actual != expected:
                    logger.error(
                        "DeepSeeNet+ checksum mismatch for %s: expected %s, got %s",
                        risk_factor,
                        expected,
                        actual,
                    )
                else:
                    logger.info("DeepSeeNet+ checksum verified: %s", risk_factor)

    def infer(self) -> InferTask:
        return lib.infers.DeepSeeNetPlus(model_folder=self.model_folder)

    def trainer(self) -> Optional[TrainTask]:
        return None

    def strategy(self) -> Union[None, Strategy, Dict[str, Strategy]]:
        return None

    def scoring_method(self) -> Union[None, ScoringMethod, Dict[str, ScoringMethod]]:
        return None
