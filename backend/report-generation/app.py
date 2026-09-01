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
    text = re.sub(r"<unused\d+>", "", text).strip()

    # MedGemma sometimes narrates its process (English chain-of-thought,
    # successive "Revised Draft" attempts) before or instead of the final
    # answer, despite enable_thinking=False and prose instructions not to.
    # The prompts wrap the requested answer in <RAPPORT>...</RAPPORT>, so
    # prefer extracting exactly that span over any heuristic.
    tag_match = re.search(r"<RAPPORT>(.*?)</RAPPORT>", text, re.IGNORECASE | re.DOTALL)
    if tag_match:
        text = tag_match.group(1).strip()
    else:
        open_tag = re.search(r"<RAPPORT>", text, re.IGNORECASE)
        if open_tag:
            # Generation was cut off before the closing tag (token limit).
            # Best-effort recovery: keep everything after the opening tag.
            print("WARNING: MedGemma output truncated before </RAPPORT>; using partial content")
            text = text[open_tag.end():].strip()
        else:
            # Older/unconstrained output: fall back to the previous
            # heading-based heuristic.
            report_heading = re.search(
                r"(?im)^(?:#{1,3}\s*)?(?:\*\*)?"
                r"(?:œil droit|oeil droit|œil gauche|oeil gauche|"
                r"synthèse bilatérale|synthese bilaterale)\s*:?(?:\*\*)?\s*$",
                text,
            )
            if report_heading:
                text = text[report_heading.start():].strip()

    text = re.sub(r"(?im)^\s*(?:thought|thinking process|raisonnement)\s*:?\s*$", "", text)
    text = re.sub(r"</?RAPPORT>", "", text, flags=re.IGNORECASE).strip()
    return _dedupe_report_text(text)


def _normalize_repeated_line(line: str) -> str:
    line = re.sub(r"^[\-*]\s+", "", line.strip().lower())
    line = re.sub(r"\*\*", "", line)
    line = re.sub(r"\s+", " ", line)
    return line.rstrip(" .;:")


def _dedupe_report_text(text: str) -> str:
    lines = []
    seen_limitations = set()
    in_limitations = False
    limitation_sentences = 0
    repeated_limitations = 0

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1].strip():
                lines.append("")
            continue

        heading = stripped.lstrip("# ").strip().lower()
        if heading == "limitations":
            in_limitations = True
            limitation_sentences = 0
            repeated_limitations = 0
            lines.append(line)
            continue
        if stripped.startswith("#") and heading != "limitations":
            in_limitations = False

        if in_limitations and heading != "limitations":
            normalized = _normalize_repeated_line(stripped)
            if normalized in seen_limitations:
                repeated_limitations += 1
                if repeated_limitations >= 2:
                    break
                continue
            seen_limitations.add(normalized)
            limitation_sentences += len(re.findall(r"[.!?](?:\s|$)", stripped))
            if limitation_sentences >= 2:
                lines.append(line)
                break

        lines.append(line)

    return "\n".join(lines).strip()


def _format_percent(value):
    if isinstance(value, (int, float)):
        return f"{value:.1%}" if value <= 1 else f"{value:.2f}%"
    return value if value not in (None, "") else "N/A"


def _probability_items(probabilities):
    if isinstance(probabilities, dict):
        return probabilities.items()
    if isinstance(probabilities, list):
        items = []
        for item in probabilities:
            if isinstance(item, dict):
                items.append((item.get("label", "?"), item.get("score")))
        return items
    return []


def format_analysis_data(report_data: dict) -> str:
    lines = []
    cls = (
        report_data.get("medgemma_dr_adjudication")
        or report_data.get("selected_dr_classification")
        or report_data.get("dr_classification")
        or report_data.get("classification")
        or {}
    )
    dr_models = report_data.get("dr_classification_models") or {}
    lesions = report_data.get("lesions") or report_data.get("quantification") or {}
    optic = report_data.get("optic_disc_cup") or {}
    glaucoma = report_data.get("glaucoma") or {}
    vessels = report_data.get("vessels") or {}
    deepseenet = report_data.get("deepseenet_plus") or {}

    if cls:
        lines.append("## Classification RD principale")
        lines.append(f"- Grade predit: {cls.get('predicted_grade') or cls.get('grade') or 'N/A'}")
        lines.append(f"- Confiance: {_format_percent(cls.get('confidence'))}")
        probabilities = cls.get("probabilities") or []
        if probabilities:
            lines.append("- Distribution des probabilites:")
            for label, score in _probability_items(probabilities):
                score = _format_percent(score)
                lines.append(f"  - {label}: {score}")

    if dr_models:
        lines.append("## Resultats individuels des classifieurs RD")
        for model_key, model_name in (("vit", "ViT"), ("clip_dr", "CLIP-DR")):
            model = dr_models.get(model_key) or {}
            if model.get("status") == "ok":
                lines.append(
                    f"- {model_name}: {model.get('grade', 'N/A')} "
                    f"(confiance: {_format_percent(model.get('confidence'))})"
                )

    if lesions:
        lines.append("## Quantification des lesions")
        lines.append(f"- Microanevrismes: {lesions.get('microaneurysms', 'N/A')}")
        lines.append(f"- Hemorragies: {lesions.get('hemorrhages', 'N/A')}")
        lines.append(
            f"- Exsudats durs: "
            f"{lesions.get('hard_exudates', lesions.get('exudates', 'N/A'))}"
        )
        lines.append(
            f"- Nodules cotonneux: "
            f"{lesions.get('soft_exudates', lesions.get('cotton_wool_spots', 'N/A'))}"
        )
        lines.append(f"- Neovascularisation: {lesions.get('neovascularization', 'N/A')}")
        lines.append(f"- Cicatrices laser: {lesions.get('laser_scars', 'N/A')}")
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

    if deepseenet:
        lines.append("## Evaluation DMLA DeepSeeNet+")
        for key, label in (
            ("drusen", "Drusen"),
            ("pigment", "Anomalies pigmentaires"),
            ("amd", "DMLA avancee"),
        ):
            factor = deepseenet.get(key) or {}
            if factor:
                lines.append(
                    f"- {label}: {factor.get('label', 'N/A')} "
                    f"(confiance: {_format_percent(factor.get('probability'))})"
                )
        patient = deepseenet.get("patient_summary") or {}
        score = patient.get("simplified_score")
        lines.append(f"- Score AREDS simplifie bilateral: {score if score is not None else 'non calculable'}")
        if deepseenet.get("conservative"):
            lines.append(
                "- Methode: aggregation conservatrice; les facteurs peuvent provenir "
                "de plusieurs images du meme oeil."
            )

    if not lines:
        return "Aucune donnee quantitative fournie."

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

    normalized_eye = str(eye or "").strip().lower()
    if any(value in normalized_eye for value in ("droit", "right", "od")):
        report_title = "Œil droit :"
    elif any(value in normalized_eye for value in ("gauche", "left", "og")):
        report_title = "Œil gauche :"
    else:
        report_title = "Œil examiné :"

    return f"""Tu es un assistant médical spécialisé en ophtalmologie.
Rédige un résumé professionnel du fond d'œil, entièrement en français.

Règles obligatoires :
- Ta réponse complète doit être uniquement : <RAPPORT>{report_title} [paragraphe]</RAPPORT>
- N'écris strictement rien avant <RAPPORT>, ni après </RAPPORT> : pas de plan, pas de brouillon, pas de vérification de longueur, pas de réflexion visible.
- Utilise les sorties des modèles, sans modifier ni inventer les valeurs.
- Résume les résultats importants sans recopier toutes les données techniques.
- N'utilise aucun mot anglais pour désigner les diagnostics ou les stades.
- N'utilise ni liste, ni tableau, ni sous-rubrique.
- Ne pose pas un diagnostic absent des données et ne déduis pas un œdème maculaire des seuls exsudats.
- Présente les résultats automatisés comme des constatations à confirmer.
- Si les classificateurs sont discordants, indique prudemment une plage de sévérité.
- Le rapport comprend exactement un titre et un seul paragraphe de 3 à 5 phrases.
- Termine le paragraphe par une recommandation ophtalmologique concise.
- Longueur cible : 70 à 120 mots.

{image_instruction}

## Patient
- Identifiant: {patient_id}
- Age: {age}
- Oeil examine: {eye}
- Date d'examen: {exam_date}

{analysis_text}

Format obligatoire (rien d'autre dans ta réponse) :
<RAPPORT>{report_title}
[Un unique paragraphe de 3 à 5 phrases résumant les lésions principales, le stade probable, les éventuelles anomalies maculaires et la recommandation.]</RAPPORT>

Rédige maintenant, directement, sans brouillon ni répétition."""


def _summary_prompt(
    patient_id: str,
    reports_by_eye: dict,
    per_eye: dict,
    patient_age: int | None = None,
) -> str:
    age = f"{patient_age} ans" if patient_age else "Non renseigne"
    eye_sections = []
    for side, label in (("right", "Oeil droit"), ("left", "Oeil gauche")):
        eye_report = (reports_by_eye or {}).get(side) or {}
        eye_data = (per_eye or {}).get(side) or {}
        dr = (
            eye_data.get("medgemma_dr_adjudication")
            or eye_data.get("selected_dr_classification")
            or eye_data.get("dr_classification")
            or {}
        )
        glaucoma = eye_data.get("glaucoma") or {}
        vessels = eye_data.get("vessels") or {}
        lesions = eye_data.get("lesions") or {}
        detail = eye_report.get("report_text") or "Non disponible"
        eye_sections.append(
            f"""## {label}
- Grade DR: {dr.get('grade', 'N/A')}
- Confiance DR: {_format_percent(dr.get('confidence'))}
- Risque glaucome: {glaucoma.get('risk', 'N/A')}
- Rapport cupule/disque: {glaucoma.get('vcdr', 'N/A')}
- Couverture lesionnelle: {_format_percent(lesions.get('coverage_pct'))}
- Couverture vasculaire: {_format_percent(vessels.get('coverage_pct'))}
- Rapport detaille:
{detail[:2400]}"""
        )

    return f"""Tu es un ophtalmologiste rédacteur.
Rédige un résumé bilatéral du fond d'œil, entièrement en français médical professionnel.

Règles obligatoires :
- Ta réponse complète doit être uniquement : <RAPPORT>Synthèse bilatérale : [paragraphe]</RAPPORT>
- N'écris strictement rien avant <RAPPORT>, ni après </RAPPORT> : pas de plan, pas de brouillon, pas de vérification de longueur, pas de réflexion visible.
- Ne recopie pas successivement les rapports de chaque œil : résume et compare.
- N'utilise aucun mot anglais pour désigner les diagnostics ou les stades.
- N'utilise ni liste, ni tableau, ni sous-rubrique.
- Ne pose pas un diagnostic absent des données et ne déduis pas un œdème maculaire des seuls exsudats.
- Présente les classifications automatisées comme des résultats à confirmer.
- En cas de discordance entre classificateurs, indique une plage prudente de sévérité.
- Mentionne une asymétrie seulement si elle est étayée par les données.
- Le rapport comprend exactement un titre et un seul paragraphe de 3 à 5 phrases.
- Termine par une recommandation ophtalmologique concise.
- Longueur cible : 80 à 130 mots.

## Patient
- Identifiant: {patient_id}
- Age: {age}

{chr(10).join(eye_sections)}

Format obligatoire (rien d'autre dans ta réponse) :
<RAPPORT>Synthèse bilatérale :
[Un unique paragraphe de 3 à 5 phrases donnant l'impression générale, comparant les deux yeux et indiquant les examens recommandés.]</RAPPORT>

Rédige maintenant, directement, sans brouillon ni répétition."""


def _analysis_prompt() -> str:
    return """Analyse cette photographie couleur du fond d'oeil.
Retourne uniquement un objet JSON valide, sans texte avant ni apres, avec cette structure:
{
  "dr_classification": {"grade": "string", "confidence": 0.0, "probabilities": [{"label": "string", "score": 0.0}]},
  "lesions": {"microaneurysms": 0, "hemorrhages": 0, "hard_exudates": 0, "soft_exudates": 0, "cotton_wool_spots": 0, "neovascularization": 0, "laser_scars": 0, "exudates": 0, "coverage_pct": 0.0},
  "glaucoma": {"vcdr": 0.0, "risk": "string", "disc_area_px": 0, "cup_area_px": 0},
  "vessels": {"coverage_pct": 0.0}
}
Si une mesure ne peut pas etre estimee de maniere fiable, utilise null."""


DR_GRADES = ["no_dr", "mild_npdr", "moderate_npdr", "severe_npdr", "proliferative_dr"]


def _adjudication_prompt(patient_id, patient_age, eye, report_data) -> str:
    payload = {
        "patient": {"patient_id": patient_id, "age": patient_age, "eye": eye},
        "selected_dr_classification": report_data.get("selected_dr_classification"),
        "dr_classification_models": report_data.get("dr_classification_models"),
        "lesions": report_data.get("lesions"),
        "optic_disc_cup": report_data.get("optic_disc_cup"),
        "glaucoma": report_data.get("glaucoma"),
        "vessels": report_data.get("vessels"),
        "deepseenet_plus": report_data.get("deepseenet_plus"),
    }
    return f"""Tu es un ophtalmologiste arbitre. Analyse l'image couleur du fond d'oeil et les sorties IA ci-dessous.
Retourne uniquement un objet JSON valide, sans markdown ni texte supplémentaire.
Ne modifie jamais les sorties originales. Le champ confidence est ton score interne non calibre entre 0 et 1.
Si les donnees sont insuffisantes, utilise status=\"insufficient_data\" et conserve comme grade le grade selected_dr_classification.

Structure obligatoire:
{{
  "status": "supported|discordant|insufficient_data",
  "grade": "no_dr|mild_npdr|moderate_npdr|severe_npdr|proliferative_dr",
  "grade_index": 0,
  "confidence": 0.0,
  "evidence": ["string"],
  "contradictions": ["string"],
  "limitations": ["string"],
  "requires_ophthalmologist_review": true
}}

Donnees:
{json.dumps(payload, ensure_ascii=False, default=str)}"""


def _normalize_adjudication(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("MedGemma adjudication is not an object")
    grade = str(value.get("grade") or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "normal": "no_dr", "no_dr": "no_dr", "mild": "mild_npdr",
        "moderate": "moderate_npdr", "severe": "severe_npdr",
        "proliferative": "proliferative_dr", "pdr": "proliferative_dr",
    }
    grade = aliases.get(grade, grade)
    if grade not in DR_GRADES:
        raise ValueError(f"Unsupported MedGemma DR grade: {grade}")
    status = str(value.get("status") or "discordant")
    if status not in {"supported", "discordant", "insufficient_data"}:
        status = "discordant"
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    normalized = {
        "status": status,
        "grade": grade,
        "grade_index": DR_GRADES.index(grade),
        "confidence": confidence,
        "calibration_status": "not_locally_calibrated",
        "evidence": [str(item) for item in (value.get("evidence") or []) if item],
        "contradictions": [str(item) for item in (value.get("contradictions") or []) if item],
        "limitations": [str(item) for item in (value.get("limitations") or []) if item],
        "requires_ophthalmologist_review": bool(value.get("requires_ophthalmologist_review", True)),
        "model_id": MODEL_ID,
        "method": "medgemma_multimodal_two_stage",
    }
    if status != "supported" or normalized["contradictions"]:
        normalized["requires_ophthalmologist_review"] = True
    return normalized


def _fallback_adjudication(report_data: dict, reason: str) -> dict:
    selected = (
        report_data.get("selected_dr_classification")
        or report_data.get("dr_classification")
        or {}
    )
    grade_index = selected.get("grade_index")
    try:
        grade_index = int(grade_index)
    except (TypeError, ValueError):
        grade_index = None
    if grade_index not in range(5):
        raw = str(selected.get("grade") or "no_dr").lower().replace(" ", "_").replace("-", "_")
        raw = {"normal": "no_dr", "mild": "mild_npdr", "moderate": "moderate_npdr", "severe": "severe_npdr", "proliferative": "proliferative_dr", "pdr": "proliferative_dr"}.get(raw, raw)
        grade_index = DR_GRADES.index(raw) if raw in DR_GRADES else 0
    return {
        "status": "insufficient_data",
        "grade": DR_GRADES[grade_index],
        "grade_index": grade_index,
        "confidence": float(selected.get("confidence") or 0.0),
        "calibration_status": "not_locally_calibrated",
        "evidence": ["Repli sur la sélection conservatrice des classifieurs"],
        "contradictions": [],
        "limitations": [reason],
        "requires_ophthalmologist_review": True,
        "model_id": MODEL_ID,
        "method": "conservative_fallback",
    }


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
        generation_kwargs = {
            "max_new_tokens": _generation_token_limit(max_new_tokens),
            "do_sample": False,
        }

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
        working_report_data = dict(report_data or {})
        if image is None:
            adjudication = _fallback_adjudication(
                working_report_data,
                "Image couleur indisponible pour l'arbitrage multimodal MedGemma",
            )
        else:
            adjudication = None
            adjudication_error = None
            for attempt in range(2):
                try:
                    prompt = _adjudication_prompt(
                        patient_id, patient_age, eye, working_report_data
                    )
                    if attempt:
                        prompt += (
                            "\nRAPPEL: réponds immédiatement avec le caractère {, "
                            "puis uniquement l'objet JSON demandé."
                        )
                    adjudication_text = self.generate_text(
                        prompt,
                        image=image,
                        max_new_tokens=min(_generation_token_limit(max_new_tokens), 512),
                    )
                    adjudication = _normalize_adjudication(
                        _extract_json(adjudication_text)
                    )
                    break
                except Exception as exc:
                    adjudication_error = exc
            if adjudication is None:
                adjudication = _fallback_adjudication(
                    working_report_data,
                    f"Arbitrage MedGemma indisponible après 2 tentatives: "
                    f"{str(adjudication_error)[:160]}",
                )
        working_report_data["medgemma_dr_adjudication"] = adjudication
        prompt = _report_prompt(
            patient_id=patient_id,
            report_data=working_report_data,
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
                "medgemma_dr_adjudication": adjudication,
            },
        }

    def generate_summary_report(
        self,
        patient_id: str,
        reports_by_eye: dict,
        per_eye: dict,
        patient_age: int | None = None,
        max_new_tokens: int | None = None,
    ) -> dict:
        prompt = _summary_prompt(
            patient_id=patient_id,
            reports_by_eye=reports_by_eye,
            per_eye=per_eye,
            patient_age=patient_age,
        )
        started_at = time.perf_counter()
        token_limit = _generation_token_limit(max_new_tokens)
        text = self.generate_text(prompt, max_new_tokens=token_limit)
        generation_time_seconds = time.perf_counter() - started_at
        return {
            "report_text": text,
            "report_html": report_text_to_html(text),
            "report_json": {
                "engine": "medgemma-1.5-4b-it",
                "report_engine": "medgemma-1.5-4b-it",
                "report_type": "bilateral_summary",
                "model": MODEL_ID,
                "used_image": False,
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


class SummaryReportRequest(BaseModel):
    patient_id: str
    reports_by_eye: dict
    per_eye: dict
    patient_age: int | None = None
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


@app.post("/summary-report")
def summary_report(req: SummaryReportRequest):
    try:
        result = medgemma.generate_summary_report(
            patient_id=req.patient_id,
            patient_age=req.patient_age,
            reports_by_eye=req.reports_by_eye,
            per_eye=req.per_eye,
            max_new_tokens=req.max_new_tokens,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MedGemma summary generation failed: {exc}")
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
