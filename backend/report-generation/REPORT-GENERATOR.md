# MedGemma Report Generator

This FastAPI service generates ophthalmology reports with Hugging Face MedGemma:

- Model: `google/medgemma-1.5-4b-it`
- Main report flow: fundus image + MONAI/DR model outputs -> French clinical report
- Fallback report flow: MONAI/DR model outputs only -> French clinical report

MedGemma access requires accepting the model terms on Hugging Face and providing credentials.
For Docker, set `HF_TOKEN` in the environment. For local development, run `huggingface-cli login` after accepting the terms.

## Endpoints

### `GET /health`

Returns service status, model id, CUDA availability, load state, and whether `HF_TOKEN` is configured.

### `POST /generate`

Generates a report from an image and model outputs.

Form fields:

- `file`: fundus image, PNG/JPEG
- `patient_id`: patient identifier
- `patient_age`: optional age
- `eye`: optional eye label
- `monai_data`: JSON string containing outputs such as `dr_classification`, `lesions`, `optic_disc_cup`, `glaucoma`, and `vessels`

Response:

```json
{
  "patient_id": "PAT-001",
  "monai_data": {},
  "report_text": "...",
  "report_html": "...",
  "report_json": {
    "engine": "medgemma-1.5-4b-it",
    "model": "google/medgemma-1.5-4b-it",
    "used_image": true
  }
}
```

### `POST /report`

Generates a report from model outputs only. This keeps compatibility with backend tasks that do not have an image available.

JSON body:

```json
{
  "patient_id": "PAT-001",
  "patient_age": 65,
  "eye": "Oeil droit (OD)",
  "report_data": {
    "dr_classification": {"grade": "moderate_npdr", "confidence": 0.91},
    "lesions": {"microaneurysms": 12, "hemorrhages": 3, "exudates": 1},
    "optic_disc_cup": {"cup_disc_ratio": 0.42},
    "vessels": {"coverage_pct": 11.2}
  }
}
```

### `POST /analyze`

Optional compatibility endpoint that asks MedGemma to return structured JSON analysis from an image only. MONAI remains the preferred source of quantitative metrics for report generation.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEDGEMMA_MODEL_ID` | `google/medgemma-1.5-4b-it` | Hugging Face model id |
| `HF_TOKEN` | unset | Hugging Face token for gated model access |
| `HF_HOME` | `/opt/hf-cache` | Hugging Face cache directory |
| `DEVICE` | `auto` | `auto`, `cuda`, or `cpu` |
| `MEDGEMMA_MAX_NEW_TOKENS` | `4096` | Report generation token limit |

## Notes

- The prompt includes the `dr_classification` output and instructs MedGemma not to invent or alter numeric values.
- `/generate` is preferred because it gives MedGemma both the fundus image and the model outputs.
- `/report` is used when no Orthanc image/series UID is available.
