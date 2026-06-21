"""XAI utilities for Grad-CAM and CLAHE image generation."""
import os, pathlib, numpy as np, base64, io, logging, traceback
from PIL import Image

logger = logging.getLogger(__name__)

def _dicom_dir(image, instance):
    uri = instance.datastore().get_image_uri(image)
    # get_image_uri returns the NIfTI file path (series_uid.nii.gz);
    # the DICOM source directory is the same path without extension.
    dcm_dir = str(pathlib.Path(str(uri)).with_suffix("").with_suffix(""))
    logger.info("DICOM dir: %s (exists=%s)", dcm_dir, os.path.isdir(dcm_dir))
    return dcm_dir

def generate_clahe(image, instance):
    """Generate CLAHE-enhanced fundus image, return base64 PNG."""
    try:
        dcm_dir = _dicom_dir(image, instance)
        dcm_files = sorted(pathlib.Path(dcm_dir).glob("*.dcm"))
        if not dcm_files:
            dcm_files = sorted(pathlib.Path(dcm_dir).glob("*"))
        if not dcm_files:
            logger.warning("CLAHE: No cached DICOM files found in %s", dcm_dir)
            return None

        from pydicom import dcmread
        from skimage import exposure

        ds = dcmread(str(dcm_files[0]))
        img_arr = ds.pixel_array

        if img_arr.ndim == 2:
            img_rgb = np.stack([img_arr] * 3, axis=-1)
        elif img_arr.shape[2] >= 3:
            img_rgb = img_arr[:, :, :3].astype(np.float32)
        else:
            img_rgb = np.stack([img_arr[:, :, 0]] * 3, axis=-1)

        clahe_img = np.zeros_like(img_rgb, dtype=np.float32)
        for c in range(3):
            ch = img_rgb[:, :, c].astype(np.float32)
            ch_min, ch_max = ch.min(), ch.max()
            if ch_max > ch_min:
                ch = (ch - ch_min) / (ch_max - ch_min)
            clahe_img[:, :, c] = exposure.equalize_adapthist(ch, kernel_size=64)

        clahe_img = (clahe_img * 255).clip(0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(clahe_img).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.warning("CLAHE failed: %s", traceback.format_exc()[:300])
        return None


def generate_gradcam(image, instance, dr_task):
    """Generate Grad-CAM heatmap overlay, return base64 PNG."""
    try:
        import torch
        import torch.nn.functional as F
        from skimage.transform import resize as sk_resize

        model = dr_task._hf_model
        model.eval()
        device = next(model.parameters()).device

        dcm_dir = _dicom_dir(image, instance)
        dcm_files = sorted(pathlib.Path(dcm_dir).glob("*.dcm"))
        if not dcm_files:
            dcm_files = sorted(pathlib.Path(dcm_dir).glob("*"))
        if not dcm_files:
            logger.warning("Grad-CAM: No cached DICOM files found in %s", dcm_dir)
            return None

        from pydicom import dcmread
        ds = dcmread(str(dcm_files[0]))
        img_arr = ds.pixel_array

        if img_arr.ndim == 2:
            img_rgb = np.stack([img_arr] * 3, axis=-1)
        elif img_arr.shape[2] >= 3:
            img_rgb = img_arr[:, :, :3].astype(np.float32)
        else:
            img_rgb = np.stack([img_arr[:, :, 0]] * 3, axis=-1)

        processor = dr_task._hf_processor
        inputs = processor(images=img_rgb.astype(np.uint8), return_tensors="pt").to(device)
        pixel_values = inputs["pixel_values"]

        last_layer = model.vit.layers[-1]
        activations = []
        gradients = []

        def fwd_hook(m, inp, out):
            if isinstance(out, tuple):
                activations.append(out[0])
            else:
                activations.append(out)

        def bwd_hook(m, grad_inp, grad_out):
            gradients.append(grad_out[0])

        with torch.enable_grad():
            model.requires_grad_(True)
            pixel_values.requires_grad_(True)
            h_fwd = last_layer.register_forward_hook(fwd_hook)
            h_bwd = last_layer.register_full_backward_hook(bwd_hook)
            outputs = model(pixel_values)
            logits = outputs.logits
            target_class = int(torch.argmax(logits, dim=1)[0])
            model.zero_grad()
            logits[0, target_class].backward()
            h_fwd.remove()
            h_bwd.remove()

        act = activations[0]
        grad = gradients[0] if gradients else None
        logger.info("Grad-CAM act shape: %s, grad shape: %s",
                     act.shape, grad.shape if grad is not None else None)

        if grad is None:
            logger.warning("Grad-CAM: gradients not captured, using raw activations")
            grad = torch.ones_like(act)

        # Handle various tensor shapes
        if act.dim() == 3:
            # (batch, seq, hidden)
            weights = grad.mean(dim=(0, 1), keepdim=True)
        elif act.dim() == 2:
            # (seq, hidden)
            weights = grad.mean(dim=0, keepdim=True)
        else:
            logger.warning("Grad-CAM: unexpected act dim %d", act.dim())
            return None

        cam = (weights * act).sum(dim=-1)
        if cam.dim() > 1:
            cam = cam.flatten()
        # Remove CLS token (first position) then reshape to grid
        cam = cam[1:] if cam.shape[0] > 1 else cam
        cam = F.relu(cam)
        side = int(np.sqrt(cam.shape[0]))
        cam = cam[: side * side].reshape(side, side)
        cam = cam.detach().cpu().numpy()
        cam = (cam - cam.min()) / (cam.max() - cam.min() + 1e-8)

        h, w = img_rgb.shape[:2]
        cam_resized = sk_resize(cam, (h, w), mode="reflect", preserve_range=True)

        heatmap_color = np.zeros((h, w, 3), dtype=np.uint8)
        heatmap_color[:, :, 0] = (cam_resized * 255).astype(np.uint8)
        overlay = (
            img_rgb.astype(np.float32) * 0.5 + heatmap_color.astype(np.float32) * 0.5
        ).clip(0, 255).astype(np.uint8)

        buf = io.BytesIO()
        Image.fromarray(overlay).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.warning("Grad-CAM failed: %s", traceback.format_exc()[:500])
        return None
