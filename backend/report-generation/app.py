import html
import io
import json
import os
import re
import time
from datetime import datetime

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel
from transformers import AutoModelForImageTextToText, AutoProcessor


MODEL_ID = os.environ.get("MEDGEMMA_MODEL_ID", "google/medgemma-1.5-4b-it")
DEVICE = os.environ.get("DEVICE", "auto")
MODEL_CACHE_DIR = os.environ.get("HF_HOME", "/opt/hf-cache")
MAX_NEW_TOKENS = int(os.environ.get("MEDGEMMA_MAX_NEW_TOKENS", "4096"))


app = FastAPI(
    title="Tele-Ophtalmo Report Generator API",
    description=(
        "API that generates ophthalmology reports with MedGemma from fundus "
        "images and MONAI/DR model outputs."
    ),
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _cuda_available() -> bool:
    return torch.cuda.is_available()


def _torch_dtype() -> torch.dtype:
    return torch.bfloat16 if _cuda_available() else torch.float32


def _device_map():
    if DEVICE == "cuda":
        if not _cuda_available():
            raise RuntimeError("DEVICE=cuda but CUDA is not available.")
        return "auto"
    if DEVICE == "cpu":
        return "cpu"
    return "auto" if _cuda_available() else "cpu"


def _decode_image(payload: bytes) -> Image.Image:
    if not payload:
        raise HTTPException(status_code=400, detail="Empty image file")
    try:
        return Image.open(io.BytesIO(payload)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}")


def _generation_token_limit(max_new_tokens: int | None = None) -> int:
    if max_new_tokens is None:
        return MAX_NEW_TOKENS
    return max(1, min(int(max_new_tokens), MAX_NEW_TOKENS))


def _clean_generated_text(text: str) -> str:
    return re.sub(r"<unused\d+>", "", text).strip()


def _format_percent(value):
    if isinstance(value, (int, float)):
        return f"{value:.1%}" if value <= 1 else f"{value:.2f}%"
    return value if value not in (None, "") else "N/A"


def format_analysis_data(report_data: dict) -> str:
    lines = []
    cls = report_data.get("dr_classification") or report_data.get("classification") or {}
    lesions = report_data.get("lesions") or report_data.get("quantification") or {}
    optic = report_data.get("optic_disc_cup") or {}
    glaucoma = report_data.get("glaucoma") or {}
    vessels = report_data.get("vessels") or {}

    if cls:
        lines.append("## Sortie du modele DR classification")
        lines.append(f"- Grade predit: {cls.get('predicted_grade') or cls.get('grade') or 'N/A'}")
        lines.append(f"- Confiance: {_format_percent(cls.get('confidence'))}")
        probabilities = cls.get("probabilities") or []
        if probabilities:
            lines.append("- Distribution des probabilites:")
            for item in probabilities:
                label = item.get("label", "?")
                score = _format_percent(item.get("score"))
                lines.append(f"  - {label}: {score}")

    if lesions:
        lines.append("## Quantification des lesions")
        lines.append(f"- Microanevrismes: {lesions.get('microaneurysms', 'N/A')}")
        lines.append(f"- Hemorragies: {lesions.get('hemorrhages', 'N/A')}")
        lines.append(f"- Exsudats: {lesions.get('exudates', 'N/A')}")
        lines.append(f"- Couverture lesionnelle: {_format_percent(lesions.get('coverage_pct'))}")

    if optic or glaucoma:
        lines.append("## Evaluation papille / glaucome")
        vcdr = optic.get("cup_disc_ratio") or glaucoma.get("vcdr")
        disc_area = optic.get("disc_area_px") or glaucoma.get("disc_area_px")
        cup_area = optic.get("cup_area_px") or glaucoma.get("cup_area_px")
        lines.append(f"- Rapport cupule/disque: {vcdr if vcdr is not None else 'N/A'}")
        lines.append(f"- Risque glaucome: {glaucoma.get('risk', 'N/A')}")
        lines.append(f"- Surface disque optique: {disc_area if disc_area is not None else 'N/A'} px")
        lines.append(f"- Surface cupule: {cup_area if cup_area is not None else 'N/A'} px")

    if vessels:
        lines.append("## Analyse vasculaire")
        lines.append(f"- Couverture / densite vasculaire: {_format_percent(vessels.get('coverage_pct'))}")

    if not lines:
        return "Aucune donnee quantitative fournie."

    lines.append("## JSON brut fourni par les modeles")
    lines.append(json.dumps(report_data, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def _report_prompt(
    patient_id: str,
    report_data: dict,
    patient_age: int | None = None,
    eye: str = "Non specifie",
    has_image: bool = False,
) -> str:
    exam_date = datetime.now().strftime("%d/%m/%Y %H:%M")
    age = f"{patient_age} ans" if patient_age else "Non renseigne"
    analysis_text = format_analysis_data(report_data)
    image_instruction = (
        "Analyse aussi l'image couleur du fond d'oeil fournie et correle tes "
        "observations visuelles avec les sorties des modeles."
        if has_image
        else "Aucune image n'est fournie dans cet appel; base le rapport sur les sorties des modeles."
    )

    return f"""Tu es un assistant medical specialise en ophtalmologie.
Redige un compte rendu de fond d'oeil en francais medical professionnel.

Regles importantes:
- Utilise les sorties des modeles fournies ci-dessous, notamment dr_classification.
- Ne modifie pas et n'invente pas les valeurs numeriques.
- Si l'image contredit ou nuance les sorties des modeles, explique-le prudemment.
- Mentionne les limites de l'analyse automatisee.
- Le rapport doit etre utile a un ophtalmologiste, pas au patient directement.

{image_instruction}

## Patient
- Identifiant: {patient_id}
- Age: {age}
- Oeil examine: {eye}
- Date d'examen: {exam_date}

{analysis_text}

Structure obligatoire avec des titres markdown:
## Constatations Cliniques
## Classification de la Retinopathie Diabetique
## Quantification des Lesions
## Evaluation du Glaucome
## Analyse Vasculaire
## Diagnostic Suspecte
## Stade de Severite
## Recommandations
## Limitations

Redige maintenant le rapport complet."""


def _analysis_prompt() -> str:
    return """Analyse cette photographie couleur du fond d'oeil.
Retourne uniquement un objet JSON valide, sans texte avant ni apres, avec cette structure:
{
  "dr_classification": {"grade": "string", "confidence": 0.0, "probabilities": [{"label": "string", "score": 0.0}]},
  "lesions": {"microaneurysms": 0, "hemorrhages": 0, "exudates": 0, "coverage_pct": 0.0},
  "glaucoma": {"vcdr": 0.0, "risk": "string", "disc_area_px": 0, "cup_area_px": 0},
  "vessels": {"coverage_pct": 0.0}
}
Si une mesure ne peut pas etre estimee de maniere fiable, utilise null."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def report_text_to_html(text: str) -> str:
    lines = text.strip().splitlines()
    parts = []
    in_list = False

    for raw in lines:
        line = raw.strip()
        if not line:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue

        if line.startswith("### "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h2>{html.escape(line[2:])}</h2>")
        elif line.startswith("- ") or line.startswith("* "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            item = html.escape(line[2:])
            item = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", item)
            parts.append(f"<li>{item}</li>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            content = html.escape(line)
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            parts.append(f"<p>{content}</p>")

    if in_list:
        parts.append("</ul>")

    return "\n".join(parts)


class MedGemmaEngine:
    def __init__(self):
        self.processor = None
        self.model = None
        self.loaded_device_map = None

    def load(self):
        if self.model is not None:
            return
        self.loaded_device_map = _device_map()
        print(f"Loading {MODEL_ID} with device_map={self.loaded_device_map}...")
        self.processor = AutoProcessor.from_pretrained(
            MODEL_ID,
            cache_dir=MODEL_CACHE_DIR,
            token=os.environ.get("HF_TOKEN"),
        )
        self.model = AutoModelForImageTextToText.from_pretrained(
            MODEL_ID,
            cache_dir=MODEL_CACHE_DIR,
            token=os.environ.get("HF_TOKEN"),
            torch_dtype=_torch_dtype(),
            device_map=self.loaded_device_map,
        ).eval()
        print(f"{MODEL_ID} loaded")

    @property
    def input_device(self):
        self.load()
        return next(self.model.parameters()).device

    def generate_text(
        self,
        prompt: str,
        image: Image.Image | None = None,
        max_new_tokens: int | None = None,
    ) -> str:
        self.load()
        content = []
        if image is not None:
            content.append({"type": "image", "image": image})
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]
        inputs = self.processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            enable_thinking=False,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.input_device)

        for key, value in list(inputs.items()):
            if torch.is_tensor(value) and torch.is_floating_point(value):
                inputs[key] = value.to(dtype=_torch_dtype())

        input_len = inputs["input_ids"].shape[-1]
        bad_words_ids = None
        tokenizer = getattr(self.processor, "tokenizer", None)
        if tokenizer is not None:
            thought_token_id = tokenizer.convert_tokens_to_ids("<unused94>")
            if isinstance(thought_token_id, int) and thought_token_id >= 0:
                bad_words_ids = [[thought_token_id]]

        generation_kwargs = {
            "max_new_tokens": _generation_token_limit(max_new_tokens),
            "do_sample": False,
        }
        if bad_words_ids:
            generation_kwargs["bad_words_ids"] = bad_words_ids

        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                **generation_kwargs,
            )
        generated = outputs[0][input_len:]
        return _clean_generated_text(
            self.processor.decode(generated, skip_special_tokens=True)
        )

    def generate_report(
        self,
        patient_id: str,
        report_data: dict,
        patient_age: int | None = None,
        eye: str = "Non specifie",
        image: Image.Image | None = None,
        max_new_tokens: int | None = None,
    ) -> dict:
        prompt = _report_prompt(
            patient_id=patient_id,
            report_data=report_data,
            patient_age=patient_age,
            eye=eye,
            has_image=image is not None,
        )
        started_at = time.perf_counter()
        token_limit = _generation_token_limit(max_new_tokens)
        text = self.generate_text(prompt, image=image, max_new_tokens=token_limit)
        generation_time_seconds = time.perf_counter() - started_at
        return {
            "report_text": text,
            "report_html": report_text_to_html(text),
            "report_json": {
                "engine": "medgemma-1.5-4b-it",
                "report_engine": "medgemma-1.5-4b-it",
                "model": MODEL_ID,
                "used_image": image is not None,
                "generation_time_seconds": round(generation_time_seconds, 3),
                "max_new_tokens": token_limit,
            },
        }

    def analyze(self, image: Image.Image) -> dict:
        text = self.generate_text(_analysis_prompt(), image=image)
        return _extract_json(text)


medgemma = MedGemmaEngine()


class ReportRequest(BaseModel):
    patient_id: str
    report_data: dict
    patient_age: int | None = None
    eye: str = "Non specifie"
    max_new_tokens: int | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "cuda_available": _cuda_available(),
        "device_map": medgemma.loaded_device_map or _device_map(),
        "model_loaded": medgemma.model is not None,
        "model_id": MODEL_ID,
        "report_engine": "medgemma-1.5-4b-it",
        "hf_token_configured": bool(os.environ.get("HF_TOKEN")),
    }


@app.on_event("startup")
def warmup_model():
    if os.environ.get("MEDGEMMA_WARMUP", "true").lower() not in {"1", "true", "yes"}:
        return
    try:
        medgemma.load()
    except Exception as exc:
        print(f"MedGemma warmup failed: {exc}")


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    image = _decode_image(await file.read())
    try:
        data = medgemma.analyze(image)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MedGemma analysis failed: {exc}")
    return JSONResponse(content={"analysis": data})


@app.post("/report")
def report(req: ReportRequest):
    try:
        result = medgemma.generate_report(
            patient_id=req.patient_id,
            patient_age=req.patient_age,
            eye=req.eye,
            report_data=req.report_data,
            max_new_tokens=req.max_new_tokens,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MedGemma report generation failed: {exc}")
    return JSONResponse(content={"patient_id": req.patient_id, "report": result})


@app.post("/generate")
async def generate(
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    monai_data: str = Form(default="{}"),
    patient_age: int | None = Form(default=None),
    eye: str = Form(default="Non specifie"),
    max_new_tokens: int | None = Form(default=None),
):
    image = _decode_image(await file.read())
    try:
        report_data = json.loads(monai_data) if monai_data else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"monai_data is not valid JSON: {exc.msg}",
        )

    try:
        result = medgemma.generate_report(
            patient_id=patient_id,
            patient_age=patient_age,
            eye=eye,
            report_data=report_data,
            image=image,
            max_new_tokens=max_new_tokens,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MedGemma report generation failed: {exc}")

    return JSONResponse(
        content={
            "patient_id": patient_id,
            "monai_data": report_data,
            **result,
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 8010)),
        workers=1,
    )
