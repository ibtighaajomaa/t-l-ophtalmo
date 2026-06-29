import io
import os
import json
import threading
from datetime import datetime

import torch
import torchvision.transforms as T
from PIL import Image
from torchvision.transforms.functional import InterpolationMode
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from huggingface_hub import snapshot_download
from transformers import AutoModel, AutoTokenizer, pipeline

from report_generator import generate_report, _extract_json, _build_html_from_sections

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
VOLMO_REPO_ID = os.environ.get("VOLMO_REPO_ID", "Yale-BIDS-Chen/VOLMO-2B")
DEVICE = os.environ.get("DEVICE", "auto")  # "auto", "cuda", or "cpu"
TORCH_DTYPE = torch.bfloat16 if torch.cuda.is_available() else torch.float32
MODEL_CACHE_DIR = os.environ.get("HF_HOME", "/opt/hf-cache")

# ---------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------
app = FastAPI(
    title="Tele-Ophtalmo Report Generator API",
    description="API that generates a clinical report by feeding VOLMO-2B both "
                "the fundus image and MONAI Label AI analysis data via .chat().",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Image preprocessing (InternVL / VOLMO architecture)
# ---------------------------------------------------------
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def build_transform(input_size: int = 448):
    return T.Compose([
        T.Lambda(lambda img: img.convert('RGB') if img.mode != 'RGB' else img),
        T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
        T.ToTensor(),
        T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])


def _resolve_device() -> torch.device:
    if DEVICE == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("DEVICE=cuda but no GPU is available.")
        return torch.device("cuda")
    if DEVICE == "cpu":
        return torch.device("cpu")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ---------------------------------------------------------
# MONAI Label data -> human-readable text block for the prompt
# ---------------------------------------------------------
def format_monai_data(monai_data: dict) -> str:
    """Turn the MONAI Label analysis JSON into a readable text block
    that gets injected into the VOLMO prompt alongside the image."""
    lines = []

    # DR Classification
    cls = monai_data.get("dr_classification") or monai_data.get("classification") or {}
    if cls:
        lines.append("## DR Classification")
        grade = cls.get("predicted_grade") or cls.get("grade") or "N/A"
        lines.append(f"- Predicted Grade: {grade}")
        probs = cls.get("probabilities", [])
        if probs:
            lines.append("- Probability distribution:")
            for p in probs:
                label = p.get("label", "?")
                score = p.get("score", 0)
                if isinstance(score, float) and score <= 1.0:
                    lines.append(f"  - {label}: {score:.0%}")
                else:
                    lines.append(f"  - {label}: {score}")
        conf = cls.get("confidence")
        if conf is not None:
            lines.append(f"- Confidence: {conf:.0%}" if isinstance(conf, float) else f"- Confidence: {conf}")

    # Lesions
    les = monai_data.get("lesions") or monai_data.get("quantification") or {}
    if les:
        lines.append("## Lesions")
        micro = les.get("microaneurysms")
        hemo = les.get("hemorrhages")
        exu = les.get("exudates")
        cov = les.get("coverage_pct")
        if micro is not None:
            lines.append(f"- Microaneurysms: {micro}")
        if hemo is not None:
            lines.append(f"- Hemorrhages: {hemo}")
        if exu is not None:
            lines.append(f"- Exudates: {exu}")
        if cov is not None:
            lines.append(f"- Coverage: {cov}%")

    # Optic Disc / Cup
    odc = monai_data.get("optic_disc_cup") or monai_data.get("glaucoma") or {}
    if odc:
        lines.append("## Optic Disc / Cup")
        disc = odc.get("disc_area_px") or odc.get("disc_area")
        cup = odc.get("cup_area_px") or odc.get("cup_area")
        cdr = odc.get("cup_disc_ratio") or odc.get("vcdr")
        if disc is not None:
            lines.append(f"- Disc Area: {disc} px")
        if cup is not None:
            lines.append(f"- Cup Area: {cup} px")
        if cdr is not None:
            lines.append(f"- Cup/Disc Ratio: {cdr}")
        risk = odc.get("risk")
        if risk:
            lines.append(f"- Glaucoma Risk: {risk}")

    # Vessels
    ves = monai_data.get("vessels") or {}
    if ves:
        lines.append("## Vessels")
        vcov = ves.get("coverage_pct")
        if vcov is not None:
            lines.append(f"- Coverage: {vcov}%")

    return "\n".join(lines) if lines else "No quantitative data provided."


# ---------------------------------------------------------
# VOLMO report -> HTML
# ---------------------------------------------------------
def report_text_to_html(text: str) -> str:
    """Convert a plain-text / markdown-ish report from VOLMO into basic HTML."""
    import re
    lines = text.strip().split("\n")
    parts = []
    in_list = False
    for raw in lines:
        line = raw.strip()
        if not line:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        # Markdown headers
        if line.startswith("### "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h2>{line[2:]}</h2>")
        elif line.startswith("- ") or line.startswith("* "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{line[2:]}</li>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            # Bold **text**
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            parts.append(f"<p>{line}</p>")
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


# ---------------------------------------------------------
# Lazy singleton for the VOLMO model
# ---------------------------------------------------------
class VolmoEngine:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.device = None
        self.model_path = None

    def load(self):
        if self.model is not None:
            return
        print("Loading VOLMO-2B model...")
        self.device = _resolve_device()
        self.model_path = snapshot_download(
            repo_id=VOLMO_REPO_ID,
            cache_dir=MODEL_CACHE_DIR,
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_path, trust_remote_code=True
        )
        self.model = AutoModel.from_pretrained(
            self.model_path,
            torch_dtype=TORCH_DTYPE,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        ).eval().to(self.device)
        print(f"VOLMO-2B loaded on device={self.device}")

    def _prepare_image(self, image: Image.Image):
        self.load()
        transform = build_transform()
        return transform(image).unsqueeze(0).to(TORCH_DTYPE).to(self.device)

    def analyze(self, image: Image.Image) -> dict:
        """Ask VOLMO to output structured JSON metrics only (no MONAI data)."""
        pixel_values = self._prepare_image(image)
        prompt = """Analysez cette photographie du fond d'œil en tant qu'ophtalmologue expert.
    Répondez UNIQUEMENT avec un objet JSON valide correspondant exactement à cette structure, sans texte supplémentaire :
    {
      "dr_classification": {"grade": "string", "confidence": 0.95, "probabilities": [{"label": "string", "score": 0.95}]},
      "lesions": {"microaneurysms": 0, "hemorrhages": 0, "exudates": 0, "coverage_pct": 0.0},
      "glaucoma": {"vcdr": 0.0, "risk": "string", "disc_area_px": 0, "cup_area_px": 0},
      "vessels": {"coverage_pct": 0.0}
    }
    Si une métrique spécifique ne peut être quantifiée, estimez-la selon la présentation clinique ou retournez null."""
        generation_config = dict(max_new_tokens=1024, do_sample=False)
        response = self.model.chat(
            self.tokenizer, pixel_values, prompt, generation_config
        )
        return _extract_json(response)

    def generate_report(
        self,
        image: Image.Image,
        monai_data: dict,
        patient_id: str,
    ) -> str:
        """Feed VOLMO both the image AND the MONAI Label analysis data via .chat(),
        asking it to write a professional clinical report in French directly."""
        pixel_values = self._prepare_image(image)
        monai_text = format_monai_data(monai_data)
        exam_date = datetime.now().strftime("%d/%m/%Y %H:%M")

        prompt = f"""Vous êtes un ophtalmologue expérimenté. Analysez cette photographie couleur du fond d'œil et rédigez un compte-rendu ophtalmologique professionnel et complet en français, détaillant les anomalies observées, le diagnostic suspecté et le stade de sévérité de la maladie.

L'image a également été pré-analisée par un système d'intelligence artificielle de segmentation et classification (MONAI Label) avec les résultats quantitatifs suivants :

{monai_text}

## Patient
- Identifiant : {patient_id}
- Date d'examen : {exam_date}

En utilisant À LA FOIS votre propre analyse visuelle de l'image du fond d'œil ET les métriques quantitatives ci-dessus, rédigez un compte-rendu clinique complet en français médical professionnel.

Ton : professionnel, clinique, précis. Utilisez la terminologie ophtalmologique française standard. Soyez rigoureux et nuancé comme un médecin.

Structurez impérativement le rapport avec les sections suivantes (utilisez les en-têtes markdown ##) :

## Constatations Cliniques
Décrivez méthodiquement ce que vous observez sur l'image (papille, vasculature rétinienne, macula, périphérie) et corréléz avec les métriques IA. Mentionnez la qualité de l'image, la netteté du cliché, et les structures visibles.

## Classification de la Rétinopathie Diabétique
Précisez le grade de RD, analysez la distribution des probabilités et la confiance du modèle. Interprétez cliniquement le résultat.

## Quantification des Lésions
Analysez le nombre et la répartition des microanévrismes, hémorragies et exsudats. Commentez le pourcentage de couverture lésionnelle et sa signification clinique.

## Évaluation du Glaucome
Interprétez le rapport cupule/disque (C/D), la surface de la papille et de la cupule. Évaluez le risque de glaucome et la nécessité d'explorations complémentaires.

## Analyse Vasculaire
Analysez la densité et la couverture vasculaire. Commentez la régularité des vaisseaux, les calibres et la présence éventuelle de néovaisseaux.

## Diagnostic Suspecté
Formulez le ou les diagnostics suspects à partir de l'ensemble des données cliniques et paracliniques disponibles. Restez nuancé et justifiez votre raisonnement.

## Stade de Sévérité
Précisez le stade de sévérité de la pathologie selon les classifications en vigueur (classification internationale de la RD, stade d'Eaux-Blanches, etc.).

## Recommandations
Proposez des recommandations cliniques claires et hiérarchisées (surveillance, consultation spécialisée, examens complémentaires, délai de suivi, contrôle des facteurs de risque systémiques).

## Limitations
Décrivez les limites de l'examen et de l'analyse automatisée (qualité de l'image, artifacts, champ de vision, fiabilité des mesures quantitatives selon la qualité du cliché).

Rédigez l'intégralité du rapport en français médical professionnel."""

        generation_config = dict(max_new_tokens=4096, do_sample=False, temperature=0.3)
        response = self.model.chat(
            self.tokenizer, pixel_values, prompt, generation_config
        )
        return response.strip()


volmo = VolmoEngine()


# ---------------------------------------------------------
# Lazy singleton for the LLaMA model (local text generation)
# ---------------------------------------------------------
class LlamaReportEngine:
    def __init__(self):
        self.pipe = None

    def load(self):
        if self.pipe is not None:
            return
        print("Loading LLaMA-3.2-3B-Instruct...")
        self.pipe = pipeline(
            "text-generation",
            model="meta-llama/Llama-3.2-3B-Instruct",
            torch_dtype=torch.float32,
            device_map="cpu",
            low_cpu_mem_usage=True,
        )
        print("LLaMA-3.2-3B-Instruct loaded on CPU")

    def generate_report(
        self,
        patient_id: str,
        patient_age: int | None,
        eye: str,
        report_data: dict,
    ) -> str:
        self.load()
        exam_date = datetime.now().strftime("%d/%m/%Y")
        cls = report_data.get("dr_classification") or {}
        les = report_data.get("lesions") or {}
        odc = report_data.get("optic_disc_cup") or {}
        gla = report_data.get("glaucoma") or {}
        ves = report_data.get("vessels") or {}

        grade = cls.get("grade", "N/A")
        confidence = cls.get("confidence")
        conf_str = f"{confidence:.1%}" if confidence is not None else "N/A"
        probs = cls.get("probabilities", [])
        prob_details = (
            ", ".join(f"{p.get('label','?')}: {p.get('score',0):.1%}" for p in probs)
            if probs
            else "N/A"
        )

        micro = les.get("microaneurysms", "N/A")
        hemo = les.get("hemorrhages", "N/A")
        exu = les.get("exudates", "N/A")
        coverage = les.get("coverage_pct", "N/A")
        cov_str = f"{coverage:.2f}%" if isinstance(coverage, (int, float)) else "N/A"

        vcdr = odc.get("cup_disc_ratio") or gla.get("vcdr", "N/A")
        risk = gla.get("risk", "N/A")
        disc_area = odc.get("disc_area_px") or gla.get("disc_area_px", "N/A")
        cup_area = odc.get("cup_area_px") or gla.get("cup_area_px", "N/A")

        vessel_cov = ves.get("coverage_pct", "N/A")
        vessel_str = f"{vessel_cov:.2f}%" if isinstance(vessel_cov, (int, float)) else "N/A"

        age_str = f"{patient_age} ans" if patient_age else "Non renseigné"

        system_prompt = (
            "Tu es un ophtalmologue expérimenté. Rédige un compte rendu ophtalmologique "
            "structuré en français médical à partir des données quantitatives fournies. "
            "Utilise UNIQUEMENT les chiffres donnés sans les inventer ni les modifier. "
            "Sois précis, professionnel et factuel."
        )

        user_prompt = f"""Génère un compte rendu ophtalmologique avec le format suivant :

COMPTE RENDU OPHTALMOLOGIQUE – FOND D'ŒIL

1. Informations patient
- Nom : {patient_id}
- Âge : {age_str}
- Date d'examen : {exam_date}
- Œil examiné : {eye}

2. Classification de la Rétinopathie Diabétique
- Grade : {grade}
- Confiance : {conf_str}
- Distribution des probabilités : {prob_details}

3. Quantification des Lésions
- Microanévrismes : {micro}
- Hémorragies : {hemo}
- Exsudats : {exu}
- Couverture lésionnelle : {cov_str}

4. Évaluation du Glaucome
- Rapport C/D (vCDR) : {vcdr}
- Risque : {risk}
- Surface disque optique : {disc_area} px²
- Surface cupule : {cup_area} px²

5. Analyse Vasculaire
- Densité vasculaire : {vessel_str}

6. Conclusion
Rédige une conclusion clinique qui synthétise le grade de rétinopathie diabétique, le risque de glaucome, le stade de sévérité, et les recommandations de suivi ophtalmologique."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        outputs = self.pipe(
            messages,
            max_new_tokens=2048,
            temperature=0.1,
            do_sample=False,
        )
        return outputs[0]["generated_text"][-1]["content"].strip()


llama_engine = LlamaReportEngine()


@app.on_event("startup")
def _warmup_volmo():
    threading.Thread(target=volmo.load, daemon=True).start()


# ---------------------------------------------------------
# Schemas
# ---------------------------------------------------------
class ReportRequest(BaseModel):
    patient_id: str
    report_data: dict


class LlamaReportRequest(BaseModel):
    patient_id: str
    patient_age: int | None = None
    eye: str = "Non spécifié"
    report_data: dict


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "device": str(_resolve_device()),
        "cuda_available": torch.cuda.is_available(),
        "volmo_loaded": volmo.model is not None,
        "llama_loaded": llama_engine.pipe is not None,
        "report_engine": "volmo-chat",
    }


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """Analyze a fundus image with VOLMO-2B and return structured JSON metrics only."""
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty image file")
    try:
        image = Image.open(io.BytesIO(payload))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    try:
        data = volmo.analyze(image)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"VOLMO analysis failed: {e}")

    return JSONResponse(content={"analysis": data})


@app.post("/report")
def report(req: ReportRequest):
    """Generate a formatted clinical report locally from already-computed analysis JSON
    (deterministic formatter, no VOLMO model needed). Useful as a fallback."""
    try:
        result = generate_report(
            report_data=req.report_data, patient_id=req.patient_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")
    return JSONResponse(content={"patient_id": req.patient_id, "report": result})


@app.post("/report-llama")
def report_llama(req: LlamaReportRequest):
    """Generate a clinical report using LLaMA-3.2-3B-Instruct locally on CPU,
    using the classification data (DR grade, lesions, glaucoma, vessels) as input."""
    try:
        text = llama_engine.generate_report(
            patient_id=req.patient_id,
            patient_age=req.patient_age,
            eye=req.eye,
            report_data=req.report_data,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"LLaMA report generation failed: {e}"
        )

    html = report_text_to_html(text)
    return JSONResponse(content={
        "report_text": text,
        "report_html": html,
        "report_json": {"engine": "llama-local"},
    })


@app.post("/generate")
async def generate(
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    monai_data: str = Form(default="{}"),
):
    """Full pipeline: feed VOLMO-2B BOTH the fundus image AND the MONAI Label
    analysis data (DR classification, lesions, optic disc/cup, vessels) via .chat(),
    and ask it to write a comprehensive clinical report directly.

    Form fields:
      - file:        the fundus image (jpg/png)
      - patient_id:  patient identifier
      - monai_data:  JSON string with the MONAI Label analysis output, e.g.:
          {
            "dr_classification": {
              "predicted_grade": "moderate_npdr",
              "probabilities": [
                {"label": "no_dr", "score": 0.01},
                {"label": "mild_npdr", "score": 0.04},
                {"label": "moderate_npdr", "score": 0.85},
                {"label": "severe_npdr", "score": 0.07},
                {"label": "proliferative_dr", "score": 0.02}
              ]
            },
            "lesions": {"microaneurysms": 12, "hemorrhages": 121, "exudates": 277, "coverage_pct": 0.8},
            "optic_disc_cup": {"disc_area_px": 678, "cup_area_px": 153, "cup_disc_ratio": 0.23},
            "vessels": {"coverage_pct": 11.2}
          }
    """
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty image file")
    try:
        image = Image.open(io.BytesIO(payload))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    # Parse the MONAI data JSON
    try:
        monai = json.loads(monai_data) if monai_data else {}
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=f"monai_data is not valid JSON: {e.msg}",
        )

    # Feed both image + MONAI data to VOLMO via .chat()
    try:
        report_text = volmo.generate_report(image, monai, patient_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"VOLMO report generation failed: {e}")

    report_html = report_text_to_html(report_text)

    return JSONResponse(
        content={
            "patient_id": patient_id,
            "monai_data": monai,
            "report_text": report_text,
            "report_html": report_html,
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
