import os
import re
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
    # Strip markdown code fences if present (```json ... ```)
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]
    # 1. strict parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. drop stray backslashes before chars that are not valid JSON escapes
    #    (valid: " \ / b f n r t u) -> fixes "\%", "\&", "\#" etc.
    cleaned = re.sub(r'\\(?!["\\/bfnrtu])', '', text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 3. lenient parse (allows unescaped control chars inside strings)
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Could not parse JSON: {e.msg}", e.doc, e.pos)


class LocalReportGenerator:
    """Generate a structured clinical report locally from VOLMO analysis JSON.
    No external API call (OpenRouter/Nemotron) is required."""

    def generate_report_text(
        self,
        patient_id: str,
        classification: dict,
        quantification: dict,
        glaucoma: dict = None,
        optic_disc: dict = None,
        vessel_data: dict = None,
    ) -> dict:
        exam_date = datetime.now().strftime("%d/%m/%Y %H:%M")
        glaucoma = glaucoma or {}
        optic_disc = optic_disc or {}
        vessel_data = vessel_data or {}

        sections: list = []

        # 1. Header
        sections.append({
            "title": "Rapport de Fond d'Œil",
            "type": "paragraph",
            "content": (
                f"Patient : {patient_id}\n"
                f"Date d'examen : {exam_date}\n"
                f"Modalité : Rétinographie couleur (fond d'œil)\n"
                f"Méthode d'analyse : VOLMO-2B (vision-language model)"
            ),
        })

        # 2. Classification DR
        cls = classification or {}
        cls_rows = [["Paramètre", "Valeur"]]
        cls_rows.append(["Grade RD", str(cls.get("grade", "Non disponible"))])
        conf = cls.get("confidence")
        cls_rows.append(["Confiance", f"{conf:.1%}" if conf is not None else "N/A"])
        for p in cls.get("probabilities", []) or []:
            cls_rows.append([
                str(p.get("label", "?")),
                f"{p.get('score', 0):.1%}",
            ])
        sections.append({
            "title": "Classification de la Rétinopathie Diabétique (RD)",
            "type": "table",
            "rows": cls_rows,
        })

        # 3. Lesions / quantification
        les = quantification or {}
        micro = les.get("microaneurysms")
        hemo = les.get("hemorrhages")
        exu = les.get("exudates")
        cov = les.get("coverage_pct")
        total = (micro or 0) + (hemo or 0) + (exu or 0)
        les_rows = [["Paramètre", "Valeur"]]
        les_rows.append(["Microanévrismes", str(micro if micro is not None else "N/A")])
        les_rows.append(["Hémorragies", str(hemo if hemo is not None else "N/A")])
        les_rows.append(["Exsudats", str(exu if exu is not None else "N/A")])
        les_rows.append(["Total lésions", str(total)])
        les_rows.append(["Couverture (%)", f"{cov:.4f}%" if cov is not None else "N/A"])
        sections.append({
            "title": "Quantification des Lésions",
            "type": "table",
            "rows": les_rows,
        })

        # 4. Glaucoma
        g = {**glaucoma, **optic_disc}
        vcdr = g.get("vcdr")
        risk = g.get("risk")
        disc_area = g.get("disc_area_px")
        cup_area = g.get("cup_area_px")
        glau_rows = [["Paramètre", "Valeur"]]
        glau_rows.append(["vCDR (rapport cupule/disque vertical)",
                          f"{vcdr:.3f}" if vcdr is not None else "Non évalué"])
        glau_rows.append(["Risque glaucome", str(risk) if risk else "Non évalué"])
        glau_rows.append(["Surface disque optique (px)",
                          str(disc_area) if disc_area is not None else "N/A"])
        glau_rows.append(["Surface cupule optique (px)",
                          str(cup_area) if cup_area is not None else "N/A"])
        if disc_area and cup_area and disc_area > 0:
            glau_rows.append(["Ratio surfaces cupule/disque",
                              f"{(cup_area / disc_area):.4f}"])
        sections.append({
            "title": "Évaluation du Glaucome",
            "type": "table",
            "rows": glau_rows,
        })

        # 5. Vessels
        v_cov = vessel_data.get("coverage_pct") if vessel_data else None
        ves_rows = [["Paramètre", "Valeur"]]
        ves_rows.append(["Densité vasculaire (%)",
                         f"{v_cov:.2f}%" if v_cov is not None else "Non évalué"])
        sections.append({
            "title": "Analyse Vasculaire",
            "type": "table",
            "rows": ves_rows,
        })

        # 6. Interpretation clinique
        interpretation = self._build_interpretation(
            cls, les, vcdr, risk, v_cov, total
        )
        sections.append({
            "title": "Interprétation Clinique",
            "type": "paragraph",
            "content": interpretation,
        })

        # 7. Recommandations
        recommendations = self._build_recommendations(cls, vcdr, risk, total)
        sections.append({
            "title": "Recommandations",
            "type": "list",
            "items": recommendations,
        })

        # 8. Limitations
        sections.append({
            "title": "Limitations",
            "type": "paragraph",
            "content": (
                "Les mesures quantitatives (vCDR, surfaces, couverture) sont estimées "
                "et peuvent varier selon la qualité de l'image."
            ),
        })

        report_html = _build_html_from_sections(sections)
        report_text = "\n\n".join(
            f"## {s.get('title', '')}\n{s.get('content', '')}"
            for s in sections if s.get("type") == "paragraph"
        )

        return {
            "report_text": report_text,
            "report_html": report_html,
            "report_json": {"sections": sections},
        }

    @staticmethod
    def _build_interpretation(cls, les, vcdr, risk, v_cov, total_lesions) -> str:
        grade = str(cls.get("grade", "indéterminé")).lower()
        parts = []
        if "no" in grade or "absence" in grade or "normal" in grade:
            parts.append(
                "Aucun signe de rétinopathie diabétique détecté sur cette image. "
                "Le fond d'œil apparaît normal sur les critères évalués."
            )
        else:
            parts.append(
                f"Rétinopathie diabétique de grade « {cls.get('grade', 'N/A')} » "
                f"détectée, avec un total de {total_lesions} lésion(s) identifiée(s)."
            )
        if vcdr is not None:
            if vcdr >= 0.7:
                parts.append(
                    f"Rapport cupule/disque vertical élevé (vCDR = {vcdr:.2f}), "
                    "évocateur d'une suspicion de glaucome."
                )
            elif vcdr >= 0.5:
                parts.append(
                    f"Rapport cupule/disque vertical modéré (vCDR = {vcdr:.2f}), "
                    "à surveiller."
                )
            else:
                parts.append(
                    f"Rapport cupule/disque vertical dans les limites normales "
                    f"(vCDR = {vcdr:.2f})."
                )
        if risk and str(risk).lower() in ("high", "élevé", "elevé", "modéré", "modere", "moderate"):
            parts.append(f"Risque glaucome évalué à « {risk} ».")
        if v_cov is not None and v_cov < 5.0:
            parts.append(
                f"Densité vasculaire faible ({v_cov:.2f}%), à interpréter selon "
                "le contexte clinique."
            )
        return " ".join(parts) if parts else "Interprétation non disponible."

    @staticmethod
    def _build_recommendations(cls, vcdr, risk, total_lesions) -> list:
        grade = str(cls.get("grade", "indéterminé")).lower()
        recs = []
        if "no" in grade or "absence" in grade or "normal" in grade:
            recs.append("Surveillance ophtalmologique annuelle de routine.")
        else:
            recs.append("Consultation ophtalmologique spécialisée recommandée.")
            if total_lesions and total_lesions > 10:
                recs.append("Évaluation de la sévérité et discussion thérapeutique.")
        if vcdr is not None and vcdr >= 0.5:
            recs.append("Mesure de la pression intra-oculaire et périmétrie (champ visuel).")
        if risk and str(risk).lower() in ("high", "élevé", "elevé"):
            recs.append("Suivi rapproché pour dépistage du glaucome.")
        recs.append("Contrôle des facteurs de risque systémiques (glycémie, TA).")
        recs.append("Validation du rapport par un ophtalmologue qualifié.")
        return recs

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
    """Generate a structured clinical report locally from VOLMO analysis JSON.
    The `api_key` parameter is kept for backward-compatibility but is ignored:
    no external API (OpenRouter) is called."""
    return LocalReportGenerator().generate_report(report_data, patient_id=patient_id)
