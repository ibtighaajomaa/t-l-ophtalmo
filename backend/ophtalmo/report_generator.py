import os
import json
import requests
from datetime import datetime

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
MODEL_ID = "nvidia/nemotron-3-super-120b-a12b:free"
MAX_NEW_TOKENS = 4096
TEMPERATURE = 0.1
TOP_P = 0.95

REPORT_SYSTEM_PROMPT = """Tu es un assistant medical specialise en ophtalmologie. Tu rediges des rapports de fond d'oeil structures et professionnels destines aux ophtalmologistes.

Tu dois TOUJOURS repondre UNIQUEMENT avec un objet JSON valide, sans texte avant ni apres.
L'objet JSON doit avoir la structure suivante:
{
  "sections": [
    {
      "title": "Titre de la section",
      "type": "paragraph",
      "content": "Texte du paragraphe"
    },
    {
      "title": "Titre de la section",
      "type": "table",
      "rows": [
        ["Colonne1", "Colonne2"],
        ["Valeur1", "Valeur2"]
      ]
    },
    {
      "title": "Titre de la section",
      "type": "list",
      "items": ["Element 1", "Element 2"]
    }
  ]
}

Regles:
- Utilise la terminologie ophtalmologique standard
- Sois precis dans les descriptions quantitatives
- Indique clairement le niveau de confiance des predictions
- Inclus systematiquement une section 'Interprétation Clinique' et 'Recommandations'
- Termine par une section 'Limitations' qui mentionne les limites de l'examen et de l'analyse automatisee"""


def _format_classification(data: dict) -> str:
    if not data:
        return "Non disponible"
    grade = data.get('grade', 'N/A')
    confidence = data.get('confidence')
    conf_str = f" (confiance: {confidence:.1%})" if confidence is not None else ""
    lines = [f"- Grade DR: {grade}{conf_str}"]
    probabilities = data.get('probabilities', [])
    if probabilities:
        lines.append("- Distribution des probabilites DR:")
        for p in probabilities:
            label = p.get('label', '?')
            score = p.get('score', 0)
            lines.append(f"  {label}: {score:.1%}")
    return "\n".join(lines)


def _format_quantification(data: dict) -> str:
    if not data:
        return "Non disponible"
    lines = []
    micro = data.get('microaneurysms')
    hemo = data.get('hemorrhages')
    exu = data.get('exudates')
    coverage = data.get('coverage_pct')
    total = (micro or 0) + (hemo or 0) + (exu or 0)
    lines.append(f"- Nombre total de lesions: {total}")
    if coverage is not None:
        lines.append(f"- Couverture totale: {coverage:.4f}%")
    if micro:
        lines.append(f"- Microaneurysmes: {micro} lesion(s)")
    if hemo:
        lines.append(f"- Hemorragies: {hemo} lesion(s)")
    if exu:
        lines.append(f"- Exsudats: {exu} lesion(s)")
    if not lines:
        return "Aucune lesion detectee"
    return "\n".join(lines)


def _format_glaucoma(data: dict, optic_disc: dict = None) -> str:
    g = data or {}
    o = optic_disc or {}
    if not g and not o:
        return "Non evalue"
    vcdr = g.get('vcdr') or o.get('cup_disc_ratio')
    risk = g.get('risk')
    disc_area = g.get('disc_area_px') or o.get('disc_area_px')
    cup_area = g.get('cup_area_px') or o.get('cup_area_px')
    lines = []
    if vcdr is not None:
        lines.append(f"- Rapport cupule/disque vertical (vCDR): {vcdr}")
    if risk:
        lines.append(f"- Risque glaucome: {risk}")
    if disc_area is not None:
        lines.append(f"- Surface disque optique: {disc_area} pixels")
    if cup_area is not None:
        lines.append(f"- Surface cupule optique: {cup_area} pixels")
    if disc_area and cup_area and disc_area > 0:
        ratio = cup_area / disc_area
        lines.append(f"- Ratio surfaces cupule/disque: {ratio:.4f}")
    return "\n".join(lines) if lines else "Non evalue"


def _format_vessels(data: dict) -> str:
    if not data:
        return "Non evalue"
    coverage = data.get('coverage_pct')
    if coverage is not None:
        return f"- Densite vasculaire: {coverage:.2f}%"
    return "Non evalue"


def _build_html_from_sections(sections: list) -> str:
    parts = []
    for section in sections:
        title = section.get("title", "")
        stype = section.get("type", "paragraph")

        if title:
            parts.append(f"<h2>{title}</h2>")

        if stype == "paragraph":
            content = section.get("content", "")
            if content:
                paragraphs = content.split("\n")
                for p in paragraphs:
                    p = p.strip()
                    if p:
                        parts.append(f"<p>{p}</p>")

        elif stype == "table":
            rows = section.get("rows", [])
            if rows and len(rows) > 1:
                parts.append("<table>")
                header = rows[0]
                parts.append("<thead><tr>" + "".join(f"<th>{c}</th>" for c in header) + "</tr></thead>")
                parts.append("<tbody>")
                for row in rows[1:]:
                    parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
                parts.append("</tbody></table>")
            elif rows and len(rows) == 1:
                parts.append("<table><tbody>")
                for row in rows:
                    parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
                parts.append("</tbody></table>")

        elif stype == "list":
            items = section.get("items", [])
            if items:
                parts.append("<ul>")
                for item in items:
                    parts.append(f"<li>{item}</li>")
                parts.append("</ul>")

    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]
    return json.loads(text)


class ReportGenerator:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "OpenRouter API key requise. "
                "Definissez OPENROUTER_API_KEY dans vos variables d'environnement "
                "ou passez-la via le parametre api_key."
            )

    def generate_report_text(
        self,
        patient_id: str,
        classification: dict,
        quantification: dict,
        glaucoma: dict = None,
        optic_disc: dict = None,
        vessel_data: dict = None,
    ) -> dict:
        classification_data = _format_classification(classification)
        segmentation_data = _format_quantification(quantification)
        glaucoma_data = _format_glaucoma(glaucoma, optic_disc)
        vessel_info = _format_vessels(vessel_data)
        exam_date = datetime.now().strftime("%d/%m/%Y %H:%M")

        user_message = f"""Genere un rapport de fond d'oeil complet base sur les donnees d'analyse suivantes:

## Donnees Patient
- ID Patient: {patient_id}
- Date d'examen: {exam_date}

## Resultats Classification IA
{classification_data}

## Resultats Segmentation et Quantification
{segmentation_data}

## Evaluation Glaucome
{glaucoma_data}

## Donnees Vasculaires
{vessel_info}

Redige le rapport complet en francais medical professionnel au format JSON specifie."""

        messages = [
            {"role": "system", "content": REPORT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        raw = self._call_api(messages)

        sections = []
        try:
            parsed = _extract_json(raw)
            sections = parsed.get("sections", [])
        except (json.JSONDecodeError, KeyError, TypeError):
            sections = [{
                "title": "Rapport de Fond d'Œil",
                "type": "paragraph",
                "content": raw,
            }]

        report_html = _build_html_from_sections(sections)
        report_text = "\n\n".join(
            s.get("content", "") for s in sections if s.get("type") == "paragraph"
        ) if any(s.get("type") == "paragraph" for s in sections) else raw

        return {
            "report_text": report_text,
            "report_html": report_html,
            "report_json": {"sections": sections},
        }

    def _call_api(self, messages: list) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/tele-ophtalmo",
            "X-Title": "Tele-Ophtalmo Report Generator",
        }

        payload = {
            "model": MODEL_ID,
            "messages": messages,
            "max_tokens": MAX_NEW_TOKENS,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
        }

        resp = requests.post(
            f"{OPENROUTER_API_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"OpenRouter API error {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenRouter API returned no choices")

        return choices[0]["message"]["content"]

    def generate_report(self, report_data: dict, patient_id: str) -> dict:
        return self.generate_report_text(
            patient_id=patient_id,
            classification=report_data.get("dr_classification", {}),
            quantification=report_data.get("lesions", {}),
            glaucoma=report_data.get("glaucoma", {}),
            optic_disc=report_data.get("optic_disc_cup", {}),
            vessel_data=report_data.get("vessels", {}),
        )


def generate_report(report_data: dict, patient_id: str, api_key: str = None) -> dict:
    generator = ReportGenerator(api_key=api_key)
    return generator.generate_report(report_data, patient_id=patient_id)
