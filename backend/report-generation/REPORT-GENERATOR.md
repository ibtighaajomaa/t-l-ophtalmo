# Report Generator API

A standalone micro-service that turns a retinal fundus image + MONAI Label AI
analysis data into a comprehensive ophthalmological clinical report.

It exposes an **HTTP API only** (API input -> API output). No files are written
to disk; everything is returned as JSON.

## How it works

The core endpoint (`/generate`) feeds **VOLMO-2B** (`Yale-BIDS-Chen/VOLMO-2B`,
InternVL architecture) **both** the fundus image **and** the MONAI Label
analysis data (DR classification, lesions, optic disc/cup, vessels) via its
`.chat()` function, with a prompt asking it to act as an ophthalmologist and
write a comprehensive clinical report:

> "Act as an expert ophthalmologist. Analyze this color fundus photograph and
> write a comprehensive clinical report detailing any abnormalities, the
> suspected diagnosis, and the disease severity stage."

VOLMO uses its visual understanding of the image **plus** the quantitative MONAI
metrics to produce the report directly — no external LLM API is called.

> No `OPENROUTER_API_KEY` or any other API key is required.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | FastAPI application (API entrypoint). |
| `main.py` | Original CLI script (kept for reference / local runs). |
| `report_generator.py` | Local deterministic report formatter (used by `/report` fallback). |
| `requirements.txt` | Python dependencies. |
| `Dockerfile` | Container build definition. |
| `.dockerignore` | Files excluded from the build context. |

---

## API Endpoints

Base URL: `http://localhost:8010`

Interactive docs: `http://localhost:8010/docs` (Swagger UI).

### `GET /health`

```json
{
  "status": "ok",
  "device": "cpu",
  "cuda_available": false,
  "volmo_loaded": false,
  "report_engine": "volmo-chat"
}
```

### `POST /analyze`

Analyze a fundus image with VOLMO-2B and return structured JSON metrics only
(no report, no MONAI data needed).

**Input:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file`| File | yes | Fundus image (jpg/png). |

**Output:**

```json
{
  "analysis": {
    "dr_classification": {"grade": "No DR", "confidence": 0.92, "probabilities": [...]},
    "lesions": {"microaneurysms": 0, "hemorrhages": 0, "exudates": 0, "coverage_pct": 0.0},
    "glaucoma": {"vcdr": 0.42, "risk": "low", "disc_area_px": 12345, "cup_area_px": 2100},
    "vessels": {"coverage_pct": 12.5}
  }
}
```

### `POST /report`

Generate a formatted clinical report from **already-computed** analysis JSON
using the local deterministic formatter (no VOLMO model, no GPU). Useful as a
fallback or when VOLMO is unavailable.

**Input:** `application/json`

```json
{
  "patient_id": "PAT-2026-0695",
  "report_data": {
    "dr_classification": {"grade": "Mild NPDR", "confidence": 0.88, "probabilities": []},
    "lesions": {"microaneurysms": 5, "hemorrhages": 2, "exudates": 1, "coverage_pct": 0.8},
    "glaucoma": {"vcdr": 0.45, "risk": "low", "disc_area_px": 12000, "cup_area_px": 2400},
    "vessels": {"coverage_pct": 11.2}
  }
}
```

**Output:**

```json
{
  "patient_id": "PAT-2026-0695",
  "report": {
    "report_text": "...",
    "report_html": "...",
    "report_json": { "sections": [ ... ] }
  }
}
```

### `POST /generate`  — main endpoint

Feeds VOLMO-2B **both** the fundus image **and** the MONAI Label analysis data
via `.chat()`, asking it to write a comprehensive clinical report directly.

**Input:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | yes | Fundus image (jpg/png). |
| `patient_id` | string | yes | Patient identifier. |
| `monai_data` | string (JSON) | no | MONAI Label analysis output as a JSON string. |

**`monai_data` JSON structure** (from MONAI Label AI analysis):

```json
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
  "lesions": {
    "microaneurysms": 12,
    "hemorrhages": 121,
    "exudates": 277,
    "coverage_pct": 0.8
  },
  "optic_disc_cup": {
    "disc_area_px": 678,
    "cup_area_px": 153,
    "cup_disc_ratio": 0.23
  },
  "vessels": {
    "coverage_pct": 11.2
  }
}
```

This gets formatted into a readable text block and injected into the VOLMO
prompt alongside the image:

```
## DR Classification
- Predicted Grade: moderate_npdr
- Probability distribution:
  - no_dr: 1%
  - mild_npdr: 4%
  - moderate_npdr: 85%
  - severe_npdr: 7%
  - proliferative_dr: 2%
## Lesions
- Microaneurysms: 12
- Hemorrhages: 121
- Exudates: 277
- Coverage: 0.8%
## Optic Disc / Cup
- Disc Area: 678 px
- Cup Area: 153 px
- Cup/Disc Ratio: 0.23
## Vessels
- Coverage: 11.2%
```

VOLMO then writes the report with sections: Constatations Cliniques,
Classification de la Rétinopathie Diabétique, Quantification des Lésions,
Évaluation du Glaucome, Analyse Vasculaire, Diagnostic Suspecté,
Stade de Sévérité, Recommandations, Limitations.

**Output:**

```json
{
  "patient_id": "PAT-2026-0695",
  "monai_data": { ... },
  "report_text": "## Constatations Cliniques\n...\n## Diagnostic Suspecté\n...\n## Recommandations\n...",
  "report_html": "<h2>Constatations Cliniques</h2><p>...</p>..."
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVICE` | `auto` | `auto`, `cuda`, or `cpu`. |
| `VOLMO_REPO_ID` | `Yale-BIDS-Chen/VOLMO-2B` | HuggingFace repo for the vision model. |
| `HF_HOME` | `/opt/hf-cache` | HuggingFace cache (mount as a volume to persist). |
| `HOST` | `0.0.0.0` | Server host. |
| `PORT` | `8010` | Server port. |

> No API key is required: the report is generated by VOLMO-2B locally.

---

## Running with Docker

### 1. Standalone

```bash
docker build -t report-generator ./backend/report-generation

docker run -d \
  --name report-generator \
  -p 8010:8010 \
  -v report-generator-hf-cache:/opt/hf-cache \
  report-generator
```

### 2. With docker-compose

```bash
docker compose up -d --build report-generator
```

### 3. GPU support

The default `Dockerfile` installs **CPU-only** torch. To use a GPU:

1. Replace the torch install line in `Dockerfile` with:

   ```dockerfile
   RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1
   ```

2. Run with GPU access:

   ```bash
   docker run --gpus all -e DEVICE=cuda ...
   ```

   or in `docker-compose.yml`:

   ```yaml
   report-generator:
     deploy:
       resources:
         reservations:
           devices:
             - driver: nvidia
               count: all
               capabilities: [gpu]
   ```

---

## Example Calls

```bash
# Health
curl http://localhost:8010/health

# Analyze only (image -> VOLMO structured JSON)
curl -X POST http://localhost:8010/analyze \
  -F "file=@sample_fundus.jpg"

# Report only (precomputed analysis -> local formatter, no VOLMO)
curl -X POST http://localhost:8010/report \
  -H "Content-Type: application/json" \
  -d '{"patient_id":"PAT-2026-0695","report_data":{"dr_classification":{"grade":"Mild NPDR","confidence":0.88,"probabilities":[]},"lesions":{"microaneurysms":5,"hemorrhages":2,"exudates":1,"coverage_pct":0.8},"glaucoma":{"vcdr":0.45,"risk":"low","disc_area_px":12000,"cup_area_px":2400},"vessels":{"coverage_pct":11.2}}}'

# Full pipeline: image + MONAI data -> VOLMO .chat() -> comprehensive report
curl -X POST http://localhost:8010/generate \
  -F "file=@sample_fundus.jpg" \
  -F "patient_id=PAT-2026-0695" \
  -F 'monai_data={"dr_classification":{"predicted_grade":"moderate_npdr","probabilities":[{"label":"no_dr","score":0.01},{"label":"mild_npdr","score":0.04},{"label":"moderate_npdr","score":0.85},{"label":"severe_npdr","score":0.07},{"label":"proliferative_dr","score":0.02}]},"lesions":{"microaneurysms":12,"hemorrhages":121,"exudates":277,"coverage_pct":0.8},"optic_disc_cup":{"disc_area_px":678,"cup_area_px":153,"cup_disc_ratio":0.23},"vessels":{"coverage_pct":11.2}}'
```

---

## Notes

- The VOLMO-2B model (~5 GB) is downloaded from HuggingFace on the first
  `/analyze` or `/generate` request and cached in `/opt/hf-cache`. Mount this
  path as a volume to avoid re-downloading on every restart.
- `/generate` is the main endpoint: it feeds VOLMO both the image and the MONAI
  Label analysis data and asks it to write the report directly via `.chat()`.
- `/report` is a fallback that uses a local deterministic formatter (no VOLMO,
  no GPU) — useful when the model is unavailable.
- `/analyze` asks VOLMO for structured JSON metrics only (no report).
- No external API or API key is needed.
- The clinical report is AI-assisted (VOLMO-2B + MONAI Label) and must be
  validated by a qualified ophthalmologist before any clinical decision.
