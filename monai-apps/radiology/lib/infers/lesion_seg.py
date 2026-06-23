import logging
from typing import Callable, Sequence

import torch
from monai.inferers import Inferer, SimpleInferer
from monai.transforms import (
    Activationsd,
    AsDiscreted,
    EnsureChannelFirstd,
    EnsureTyped,
    LoadImaged,
    Resized,
    ScaleIntensityRanged,
)

from monailabel.interfaces.tasks.infer_v2 import InferType
from monailabel.tasks.infer.basic_infer import BasicInferTask
from monailabel.transform.post import Restored

from .optic_disc_cup import Ensure3ChannelRGBd, SqueezeDepthd

logger = logging.getLogger(__name__)


class LesionSeg(BasicInferTask):
    def __init__(
        self,
        path,
        network=None,
        type=InferType.SEGMENTATION,
        labels=None,
        dimension=2,
        description="DeepLabV3+ based retinal lesion segmentation (DDR dataset)",
        **kwargs,
    ):
        super().__init__(
            path=path,
            network=network,
            type=type,
            labels=labels,
            dimension=dimension,
            description=description,
            load_strict=True,
            **kwargs,
        )

    def pre_transforms(self, data=None) -> Sequence[Callable]:
        return [
            LoadImaged(keys="image"),
            EnsureTyped(keys="image", device=data.get("device") if data else None),
            EnsureChannelFirstd(keys="image"),
            Ensure3ChannelRGBd(keys="image"),
            SqueezeDepthd(keys="image"),
            Resized(keys="image", spatial_size=(512, 512), mode="bilinear"),
            ScaleIntensityRanged(keys="image", a_min=0, a_max=255, b_min=0.0, b_max=1.0, clip=True),
        ]

    def inferer(self, data=None) -> Inferer:
        return SimpleInferer()

    def run_inferer(self, data, convert_to_batch=True, device="cuda"):
        inferer = self.inferer(data)
        network = self._get_network(device, data)
        inputs = data[self.input_key]
        inputs = inputs if torch.is_tensor(inputs) else torch.from_numpy(inputs)
        inputs = inputs[None] if convert_to_batch else inputs
        inputs = inputs.to(torch.device(device))

        with torch.no_grad():
            outputs = inferer(inputs, network)

        if convert_to_batch:
            outputs = outputs[0]

        data[self.output_label_key] = outputs
        data[self.output_json_key] = {
            "label_info": [
                {"name": "microaneurysms", "color": [255, 50, 50]},
                {"name": "hemorrhages", "color": [50, 50, 255]},
                {"name": "hard_exudates", "color": [255, 255, 50]},
                {"name": "soft_exudates", "color": [255, 165, 0]},
            ]
        }
        return data

    def inverse_transforms(self, data=None):
        return []

    def post_transforms(self, data=None) -> Sequence[Callable]:
        return [
            EnsureTyped(keys="pred", device=data.get("device") if data else None),
            Activationsd(keys="pred", softmax=True),
            AsDiscreted(keys="pred", argmax=True),
            Restored(keys="pred", ref_image="image"),
        ]
