"""
FTHNet API - FastAPI server for Fundus Image Quality Assessment
===============================================================
Deploy FTHNet as a REST API for real-time quality scoring of fundus images.

Usage:
    export FTHNET_WEIGHTS=./pretrained_weight/net_g_226264S4.pth
    python fthnet_api.py

Test:
    curl -X POST "http://localhost:8000/predict" \
         -H "accept: application/json" \
         -F "file=@image.jpg"

Author: FTHNet Deployment Script (auto-generated)
"""

import sys
import os
import io
import time
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# 1. Patch SoftPool if not installed (fallback to AvgPool2d)
# ---------------------------------------------------------------------------
try:
    import softpool_cuda
    from SoftPool import SoftPool2d
except ImportError:
    print("[WARN] SoftPool not found. Using AvgPool2d fallback. "
          "For best results, install SoftPool: https://github.com/alexandrosstergiou/SoftPool")

    class _FakeSoftPoolCuda:
        pass

    class SoftPool2d(nn.AvgPool2d):
        """Fallback when native SoftPool is unavailable."""
        def __init__(self, kernel_size, stride=None, padding=0):
            super().__init__(kernel_size, stride, padding)

    # Inject into sys.modules so fthnet4_arch can import them
    sys.modules['softpool_cuda'] = type(sys)('softpool_cuda')
    sys.modules['SoftPool'] = type(sys)('SoftPool')
    sys.modules['SoftPool'].SoftPool2d = SoftPool2d

# ---------------------------------------------------------------------------
# 2. Add BasiQA to path and import FTHNet4
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from basiqa.archs.fthnet4_arch import FTHNet4  # noqa: E402

# ---------------------------------------------------------------------------
# 3. Target Network (copied from hyperiqa_model.py for standalone use)
# ---------------------------------------------------------------------------
class TargetFC(nn.Module):
    """
    Fully connection operations for target net with dynamic weights per image.
    Uses grouped convolution to apply individual weights & biases per batch item.
    """
    def __init__(self, weight, bias):
        super(TargetFC, self).__init__()
        self.weight = weight
        self.bias = bias

    def forward(self, input_):
        input_re = input_.view(-1, input_.shape[0] * input_.shape[1], input_.shape[2], input_.shape[3])
        weight_re = self.weight.view(
            self.weight.shape[0] * self.weight.shape[1],
            self.weight.shape[2],
            self.weight.shape[3],
            self.weight.shape[4]
        )
        bias_re = self.bias.view(self.bias.shape[0] * self.bias.shape[1])
        out = F.conv2d(
            input=input_re,
            weight=weight_re,
            bias=bias_re,
            groups=self.weight.shape[0]
        )
        return out.view(input_.shape[0], self.weight.shape[1], input_.shape[2], input_.shape[3])


class TargetNet(nn.Module):
    """Target network for quality prediction (5 FC layers with Sigmoid)."""
    def __init__(self, paras):
        super(TargetNet, self).__init__()
        self.l1 = nn.Sequential(
            TargetFC(paras['target_fc1w'], paras['target_fc1b']),
            nn.Sigmoid(),
        )
        self.l2 = nn.Sequential(
            TargetFC(paras['target_fc2w'], paras['target_fc2b']),
            nn.Sigmoid(),
        )
        self.l3 = nn.Sequential(
            TargetFC(paras['target_fc3w'], paras['target_fc3b']),
            nn.Sigmoid(),
        )
        self.l4 = nn.Sequential(
            TargetFC(paras['target_fc4w'], paras['target_fc4b']),
            nn.Sigmoid(),
            TargetFC(paras['target_fc5w'], paras['target_fc5b']),
        )

    def forward(self, x):
        q = self.l1(x)
        q = self.l2(q)
        q = self.l3(q)
        q = self.l4(q).squeeze()
        return q


# ---------------------------------------------------------------------------
# 4. Predictor wrapper
# ---------------------------------------------------------------------------
class FTHNetPredictor:
    """
    Wrapper for FTHNet inference.
    Loads the hypernetwork weights and runs the full pipeline:
    HyperNetwork -> TargetNet (dynamic weights) -> Quality Score
    """
    def __init__(
        self,
        weights_path: str,
        device: Optional[str] = None,
        embed_dim: int = 64,          # 64 for FTHNet-L, 32 for FTHNet-S
        depths=None,
        num_heads=None,
        window_size: int = 12,
        ffa_out_ch: int = 32,
        tn_in_ch: int = 384,
        hyper_in_ch: int = 384,
    ):
        if device is None:
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.device = torch.device(device)
        print(f"[INFO] Using device: {self.device}")

        if depths is None:
            depths = [2, 2, 6, 2]
        if num_heads is None:
            num_heads = [2, 4, 8, 16]

        self.full_score = 100.0
        self.image_size = 384

        # ImageNet normalization (used in FQS training)
        self.mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

        # Build hypernetwork
        print(f"[INFO] Building FTHNet4 (embed_dim={embed_dim}) ...")
        self.net_g = FTHNet4(
            out_ch=1,
            ffa_out_ch=ffa_out_ch,
            tn_in_ch=tn_in_ch,
            hyper_in_ch=hyper_in_ch,
            embed_dim=embed_dim,
            depths=depths,
            num_heads=num_heads,
            window_size=window_size,
            drop_rate=0.0,
            attn_drop_rate=0.0,
            drop_path_rate=0.1,
        )
        self.net_g.to(self.device)

        # Load pretrained weights
        weights_path = Path(weights_path)
        if not weights_path.exists():
            raise FileNotFoundError(
                f"Weights not found: {weights_path}\n"
                f"Please download from https://drive.google.com/drive/folders/"
                f"1gXaa77aARo1sdqky3_81JD6ofL17fGUU?usp=sharing"
            )

        print(f"[INFO] Loading weights from {weights_path} ...")
        checkpoint = torch.load(weights_path, map_location=self.device)

        # Handle possible checkpoint keys: 'params', 'params_ema', or raw state_dict
        if isinstance(checkpoint, dict):
            state_dict = checkpoint.get(
                'params',
                checkpoint.get('params_ema', checkpoint)
            )
        else:
            state_dict = checkpoint

        # Remove 'module.' prefix if present (from DistributedDataParallel)
        new_state_dict = {}
        for k, v in state_dict.items():
            name = k[7:] if k.startswith('module.') else k
            new_state_dict[name] = v

        self.net_g.load_state_dict(new_state_dict, strict=False)
        self.net_g.eval()
        print("[INFO] Model loaded successfully.")

    def preprocess(self, image: Image.Image) -> torch.Tensor:
        """Resize, convert to tensor, and normalize."""
        image = image.convert('RGB')
        image = image.resize((self.image_size, self.image_size), Image.BICUBIC)
        # PIL -> numpy [H, W, C] -> tensor [1, C, H, W]
        img_np = np.array(image).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0).to(self.device)
        # Normalize with ImageNet stats
        img_tensor = (img_tensor - self.mean.to(self.device)) / self.std.to(self.device)
        return img_tensor

    @torch.no_grad()
    def predict(self, image: Image.Image) -> float:
        """
        Run inference on a single PIL image.
        Returns: quality score in [0, 100].
        """
        img_tensor = self.preprocess(image).to(self.device)

        hyper_out = self.net_g(img_tensor)
        model_target = TargetNet(hyper_out).to(self.device)
        for param in model_target.parameters():
            param.requires_grad = False

        output = model_target(hyper_out['target_in_vec'])
        score = output.item() * self.full_score
        return float(score)


# ---------------------------------------------------------------------------
# 5. FastAPI Application
# ---------------------------------------------------------------------------
try:
    from fastapi import FastAPI, File, UploadFile, HTTPException
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError:
    raise ImportError(
        "FastAPI and uvicorn are required. Install with:\n"
        "    pip install fastapi uvicorn python-multipart"
    )

app = FastAPI(
    title="FTHNet Fundus Quality API",
    description="Real-time fundus image quality assessment using FTHNet",
    version="1.0.0",
)

predictor: Optional[FTHNetPredictor] = None


@app.on_event("startup")
async def startup_event():
    """Initialize model on startup."""
    global predictor
    weights_path = os.environ.get(
        'FTHNET_WEIGHTS',
        str(SCRIPT_DIR / 'pretrained_weight' / 'net_g_226264S4.pth')
    )
    embed_dim = int(os.environ.get('FTHNET_EMBED_DIM', '64'))  # 32 for S, 64 for L

    predictor = FTHNetPredictor(
        weights_path=weights_path,
        embed_dim=embed_dim,
    )
    print("[INFO] API ready.")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy" if predictor is not None else "loading",
        "model_loaded": predictor is not None,
        "device": str(predictor.device) if predictor else None,
    }


@app.post("/predict")
async def predict_endpoint(file: UploadFile = File(...)):
    """
    Upload a fundus image and receive a quality score.

    - **file**: Fundus image (JPG, PNG, BMP, etc.)
    - Returns: quality_score (0-100), quality_category, inference_time_ms
    """
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet")

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    start = time.time()
    score = predictor.predict(image)
    infer_time = (time.time() - start) * 1000.0

    # Classification categories per FQS paper
    if score >= 80:
        category = "Good"
    elif score >= 60:
        category = "Usable"
    else:
        category = "Reject"

    return JSONResponse({
        "filename": file.filename,
        "quality_score": round(score, 2),
        "quality_category": category,
        "inference_time_ms": round(infer_time, 2),
    })


@app.post("/predict_batch")
async def predict_batch_endpoint(files: list[UploadFile] = File(...)):
    """
    Batch prediction for multiple images.
    """
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet")

    results = []
    for f in files:
        try:
            contents = await f.read()
            image = Image.open(io.BytesIO(contents))
            score = predictor.predict(image)
            if score >= 80:
                category = "Good"
            elif score >= 60:
                category = "Usable"
            else:
                category = "Reject"
            results.append({
                "filename": f.filename,
                "quality_score": round(score, 2),
                "quality_category": category,
                "status": "ok",
            })
        except Exception as e:
            results.append({
                "filename": f.filename,
                "error": str(e),
                "status": "error",
            })
    return JSONResponse({"results": results})


# ---------------------------------------------------------------------------
# 6. CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FTHNet API Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--weights", type=str, default=None, help="Path to .pth weights")
    parser.add_argument("--embed-dim", type=int, default=64, help="64 for FTHNet-L, 32 for FTHNet-S")
    args = parser.parse_args()

    if args.weights:
        os.environ['FTHNET_WEIGHTS'] = args.weights
    if args.embed_dim:
        os.environ['FTHNET_EMBED_DIM'] = str(args.embed_dim)

    uvicorn.run(app, host=args.host, port=args.port)
