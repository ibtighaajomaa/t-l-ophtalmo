# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Télé-Ophtalmo: a tele-ophthalmology platform (Tunisian Ministry of Health) for remote reading of fundus photographs (DICOM modality **OP**). Retinal cameras in regional hospitals push DICOM to an Orthanc PACS; an AI pipeline (image quality, eye laterality, optic disc/cup, vessel, lesion and neovascularization segmentation, diabetic-retinopathy grading, MedGemma report drafting) runs automatically; ophthalmologists then read the study in an embedded OHIF viewer and sign a report. A hospital DMI/CIMS system pushes/pulls exams through the token-protected `/api/dmi/` API.

Everything runs as one Docker Compose stack (`docker-compose.yml` at the repo root). There is no non-Docker dev setup for the backend or MONAI; nginx on port 80 is the single public entry point. UI text, comments, commit messages and generated reports are mostly French.

## Common commands

All from the repo root unless noted. Docker Compose v2 (`docker compose`, not `docker-compose`).

```bash
docker compose up -d --build                      # full stack (first build is very slow: OHIF + MONAI images)
docker compose ps
docker compose logs -f backend celery-worker      # also: celery-report-worker, celery-beat, monai-label, report-generator

# backend, celery-worker, celery-report-worker and celery-beat are all built from ./backend — rebuild all four after backend changes
docker compose up -d --build backend celery-worker celery-report-worker celery-beat

# OHIF is compiled from source; rebuild after touching MONAILabel/plugins/ohifv3/**, ohif/extensions/**, ohif/patches/** or ohif/Dockerfile
docker compose build ohif && docker compose up -d ohif
# ohif/default-app-config.js is bind-mounted at runtime: config-only changes just need `docker compose restart ohif`

# monai-apps/ is bind-mounted into the monai-label container: code changes need a restart, dependency changes a rebuild
docker compose restart monai-label
docker compose build monai-label && docker compose up -d monai-label
```

Django (run inside the container — it needs Postgres/Redis/Keycloak on the compose network):

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py makemigrations ophtalmo
docker compose exec backend python manage.py shell
docker compose exec backend python manage.py reset_segmentation --study <StudyInstanceUID>    # or --all-failed
docker compose exec backend python manage.py test_fthnet --orthanc-study <orthanc-id|StudyUID>  # run the quality model on a study
# fire a beat task by hand
docker compose exec backend python manage.py shell -c "from ophtalmo.tasks import tache_auto_quality; tache_auto_quality.delay()"
```

Tests:

```bash
# Django tests (unittest TestCase; Orthanc/MONAI/report-generator are mocked). Always pass app labels:
# with no label the runner also imports the ad-hoc backend/test_*.py scripts, which hit Keycloak/SMTP.
docker compose exec backend python manage.py test ophtalmo users
docker compose exec backend python manage.py test ophtalmo.tests.AutoSegmentationTaskTest.test_all_models_succeed
# backend/ophtalmo/test_dual_dr_analysis.py is pytest-style; pytest is NOT installed in the backend image.

# MONAI Label app tests (pytest is in the monai-label image; the app is mounted at /opt/monai/apps/radiology)
docker compose exec monai-label python3 -m pytest /opt/monai/apps/radiology/tests -q
docker compose exec monai-label python3 -m pytest /opt/monai/apps/radiology/tests/test_clip_dr.py::test_preprocess_clip_dr_is_deterministic
```

Frontend (`frontend/sight-bridge-main`, Node 22, npm; no test suite):

```bash
npm install
npm run dev        # Vite dev server. API calls are relative (/api, /ohif, /auth …), so they only resolve behind the nginx container
npm run build      # TanStack Start / Nitro node-server build → .output/ (what the Docker image runs)
npm run lint       # eslint (typescript-eslint + react-hooks + prettier)
npm run format
```

Gitignored model weights (`monai-label/models/**`, BigEye lesion model) are fetched with `tools/setup_vascx_fovea.sh` (needs git-xet) and `tools/setup_bigeye_neovascularization.sh`. `monai-apps/radiology/model/pretrained_eye_laterality.hdf5` is Git LFS.

## Architecture

### Services and URL map (`nginx/default.conf`)

| Path on :80 | Service | Notes |
|---|---|---|
| `/` | `frontend` — TanStack Start SSR, node :3000 | React 19 / Vite 7 / Tailwind 4 / shadcn |
| `/api/`, `/django-admin/`, `/static/`, `/oidc/` | `backend` — Django 5 + DRF, gunicorn :8001 | `/api/dmi/` hits the same backend but is IP-allowlisted in nginx |
| `/auth/` | `keycloak` 23 — realm `HopitalRealm`, `KC_HTTP_RELATIVE_PATH=/auth` | admin console also on host :8180 |
| `/ohif/` | `ohif` — custom OHIF 3.11 build | |
| `/orthanc-container/` | `orthanc-container` — Orthanc 25.8 + DICOMweb | DICOM C-STORE on host :4242, AET `Orthanc` |
| `/orthanc-plugin/` | `orthanc-plugin` | second Orthanc on the same storage volume + `orthanc-index` Postgres; only for its built-in OHIF/Stone viewers |
| `/monai/` | `monai-label` — MONAI Label :8000, `--root_path /monai` | host :8002 |
| — | `report-generator` — FastAPI + MedGemma :8010 | not proxied; called by `celery-report-worker` |
| — | `redis` (Celery broker db0, Django cache db1), `postgres-django`, `postgres-keycloak`, `mailpit` (UI :8025) | |

The public IP `193.95.31.196` is hardcoded in `docker-compose.yml` (Orthanc → OHIF public roots), `backend/config/settings.py` (OIDC endpoints, `KC_ADMIN_URL`), `backend/init_kc.py` (redirect URIs) and `frontend/sight-bridge-main/src/lib/keycloak.ts`. Moving hosts means updating all of them.

Config: the root `.env` (`HF_TOKEN` for the gated MedGemma model, `DMI_API_TOKEN`, `CLIP_DR_*`) is read by compose; `backend/.env` is read by `settings.py` through python-dotenv. Most other credentials are literal in `docker-compose.yml`.

### Backend (`backend/`)

- `config/` — settings, `celery.py` (task autodiscovery; a `worker_ready` hook enqueues the watchdog), `email_backend.py` (SMTP backend with certificate verification disabled, for the RNS relay).
- `users/` — Keycloak glue. `authentication.KeycloakAuthentication` verifies the Bearer JWT against the realm public key, sets `request.roles` from `realm_access.roles` and auto-creates a Django `User` keyed by email. **On any failure it returns `None` (anonymous) instead of raising 401.** `users/views.py` relays login (password grant), password reset, user CRUD and calendar sessions to the Keycloak admin API. Realm roles are `ADMIN_SYSTEME`, `CHEF_SERVICE`, `OPHTALMOLOGUE`, `RESIDENT` (created by `init_kc.py`) and are mapped to app roles `Admin`/`Chef`/`Medecin`/`Resident` stored in `Profil.role`. `users/permissions.py` is unused and checks names (`ADMIN`, `MEDECIN`) that don't match the realm roles.
- `ophtalmo/` — the domain. `models.Exam` is one worklist row: business `status` (`En attente` → `En cours` → `Interprété`) plus three independent pipeline states — `quality_status`, `segmentation_status`, `report_generation_status` — each `pending/in_progress/completed/failed` with `*_task_id`, `*_heartbeat_at`, `*_current_step` consumed by the watchdog. Other models: `ImageQualityAssessment`, `AnalysisReport` (raw AI output in `report_json`; its `series_instance_uid` field actually holds the StudyInstanceUID or Orthanc study id), `MedicalReport` + `MedicalReportVersion` (doctor-facing, signable, DOCX export via `docx_export.py`), `DoctorNote`, `CalendarSession`, `DMIAuditLog`, `DicomModalitySite`, `ExamStatusHistory` (written by `signals.py`).
- Container entrypoint (`entrypoint.sh`): wait for Keycloak → `init_kc.py` (idempotent realm/client/roles) → migrate → superuser → collectstatic → gunicorn (4 workers, 600 s timeout).
- Many views in `ophtalmo/views.py` are deliberately `AllowAny`: Orthanc/MONAI webhooks, sync, `run-analysis`, `composite-segmentation`, `generate-report`, and the DMI endpoints (guarded by the `X-DMI-Service-Token` header == `DMI_API_TOKEN` plus the nginx IP allowlist; see `dmi_integration.py`).
- `test_*.py`, `trace*.py`, `fix_*.py`, `check_*.py`, `patch_views.py` at the repo root and in `backend/` are one-off debugging scripts, not part of the app.

### Automatic AI pipeline (Celery)

Two workers: `celery-worker` (default queue) and `celery-report-worker` (`-Q reports -c 1`, so MedGemma handles one report at a time). `celery-beat` uses `DatabaseScheduler`: `CELERY_BEAT_SCHEDULE` in settings seeds the DB, and entries can then be edited in `/django-admin/`.

1. **Ingest** — a camera C-STOREs to Orthanc; `orthanc/on_stable_study.lua` POSTs the study to `/api/exams/orthanc-webhook/`, which creates the `Exam` and resolves the sending site from the modality IP/AET (`orthanc_origin.py`: `DicomModalitySite` table first, then hardcoded maps). `tache_sync_orthanc_incremental` (60 s) and `POST /api/exams/sync-orthanc/` are the fallbacks.
2. **Quality** — `tache_auto_quality` (60 s) runs FTHNet4 in-process on CPU (`fthnet_cpu.py`, weights under `backend/QualiteOpht/UserschiheAppDataLocalTempBasiQA/pretrained_weight/`) → `ImageQualityAssessment`; score ≥70 good, 40–70 acceptable, <40 bad.
3. **Segmentation / analysis** — `tache_auto_segmentation` (5 min; Redis lock `ophtalmo:auto_segmentation_running`; batch of 10; 3 retries via `_retry_or_fail_segmentation`). For every OP series of the study it prepares a MONAI cache dir (`_prepare_monai_series_cache`; `inject_op_geometry` adds synthetic ImagePosition/Orientation/FrameOfReferenceUID so 2D SEGs align in OHIF), runs eye laterality (the DICOM `Laterality` tag wins over the model), then calls MONAI Label `POST /infer/<model>` for `optic_disc_cup`, `vessel_seg`, `lesion_seg`, `neovascularization_seg`, `fovea_detection`, `deepseenet_plus`, `clip_dr_classification`. Prior AI SEG series are deleted (`_delete_prior_ai_seg_series`) and the new DICOM-SEGs are pushed to Orthanc by the patched MONAI Label. Per-series results are merged per eye by `analysis_utils.aggregate_per_eye` into `AnalysisReport.report_json`; then `tache_generate_ai_report` is queued and `tache_distribution` is fired.
4. **Report** — `tache_generate_ai_report` (queue `reports`) calls `report-generator` per eye (`/generate` with the fundus image rendered by Orthanc, `/report` when no image is available, `/summary-report` for the bilateral summary; prompts/text in `report_utils.py`) and writes a draft `MedicalReport` + version.
5. **Distribution** — `distribution.py` assigns `En attente` exams to doctors (urgent first, then oldest, regional fairness, max `MAX_CHARGE_PAR_MEDECIN`=30, `Profil.is_disponible`, role in `ROLES_MEDECIN`). `tache_distribution` is not on the beat schedule: it is triggered after segmentation, from the Orthanc webhook/sync and exam-creation views, and by `POST /api/exams/distribuer/`. `tache_verification_24h` (midnight) reassigns exams whose doctor became unavailable, sends reminders, resets exams with no session that day and re-runs distribution.
6. **Watchdog** — `tache_watchdog_traitements` (5 min, and on worker start) resets `in_progress` states whose heartbeat is stale and whose task id is unknown to Celery.

The frontend "Analyse IA" buttons call the manual equivalents (`run-analysis`, `composite-segmentation`, `generate-report`, `distribuer`).

### MONAI Label (`monai-apps/radiology`, container `monai-label`)

Standard MONAI Label radiology-app layout: each model is a `lib/configs/<name>.py` (`TaskConfig`: weight paths, labels) plus a `lib/infers/<name>.py` (`BasicInferTask` subclass). Only models named in the compose `command` (`--conf models …`) are loaded; the upstream spleen/vertebra/deepedit configs and `dr_classification`/`dino2_dr_classification` are present but disabled. `composite_seg` runs OD/OC + lesions + vessels + fovea in one call. The datastore is Orthanc DICOMweb. Weights live in `monai-apps/radiology/model/` (tracked) or `monai-label/models/` and `deepseenet-plus/models/` (mounted read-only, gitignored). `DOCUMENTATION_MODELES_IA.md` is the reference sheet for every model (architecture, dataset, published metrics, checkpoint names).

Two layers of patches are applied to the *installed* `monailabel` package at container start by `monai-apps/patch_monailabel.py` (see the compose `command`): `datastore/utils/convert.py` (synthetic geometry, FrameOfReferenceUID, 2D mask dimension fixes, push SEG to Orthanc) and `endpoints/infer.py` (`/infer/analyze` single-instance analysis, cache handling). `tools/patch_monai_*.py` are the individual patch sources. To change how SEGs are written or how `/infer` caches OP series, edit these patch scripts, not the package. The image is CPU-only (TensorFlow-CPU for the Keras laterality model, a pinned OpenAI CLIP commit, `retinalysis-inference` for VascX fovea).

### OHIF (`ohif/`, `MONAILabel/plugins/ohifv3/`)

`ohif/Dockerfile` clones OHIF v3.11.0 and MONAILabel `6ed8f8c`, overlays the repo copies of the MONAI Label extension/mode (`MONAILabel/plugins/ohifv3/extensions|modes/monai-label` — this is where the "AI Analysis" panel, `AiAnalysisPanel.tsx`, lives), adds `ohif/extensions/iframe-bridge` (postMessage bridge to the worklist) and applies `ohif/patches/*.patch` with `git apply` (several are written to tolerate being already applied — keep that pattern when adding one). `pluginConfig.json` is rewritten with `jq` to keep only the longitudinal, segmentation and monai-label modes; the mode's CT/MR `isValidMode` check is sed-patched to accept OP; the service worker is disabled. Runtime config is `ohif/default-app-config.js` (routerBasename `/ohif`, dicomweb → `/orthanc-container/dicom-web`, Ministry logo, OP lesion colour-legend overlay). The extension reaches MONAI at `window.location.origin + '/monai/'`.

### Frontend (`frontend/sight-bridge-main`)

Lovable-generated TanStack Start app; file-based routes in `src/routes` (`_app.*` = protected layout with `Sidebar`; `routeTree.gen.ts` is generated — don't edit). Auth: `src/lib/auth-context.tsx` posts to `/api/auth/login/`, keeps the Keycloak access token in `localStorage["teleoph.token"]` and decodes roles from it; `exam-api.ts` adds the Bearer header and maps API snake_case to camelCase. `src/lib/mock-worklist.ts` holds the shared `Exam`/status TS types despite its name. `/_app/worklist/$id` embeds OHIF in an iframe (`/ohif/viewer?StudyInstanceUIDs=…`) and drives it through `src/lib/ohif-bridge.ts` ↔ the iframe-bridge extension. `src/lib/keycloak.ts` (keycloak-js, public client `hopital-frontend`) exists but the real login path is the backend relay.

## Repository quirks

- `MONAILabel/`, `backend/QualiteOpht/UserschiheAppDataLocalTempBasiQA/` (BasiQA/FTHNet) and `deepseenet-plus/` (untracked, keeps its own `.git`) are vendored upstream repos flattened into this one; only the paths mentioned above are used.
- `backup_django.sql`, `backup_keycloak.sql`, `backup_orthanc.sql`, `orthanc_storage_backup.tar.gz` are committed snapshots (`docker compose exec -T postgres-django pg_dump -U django teleophtalmo > backup_django.sql`, etc.).
- Files literally named `=0.4.5`, `=1.1.1`, … are stray pip artefacts. `Eye-laterality-detection/`, `monai-label/cache/`, `monai-label/models/` are gitignored.
- `frontend/Dockerfile` is unused; compose builds `frontend/sight-bridge-main/Dockerfile`.
- Django `SECRET_KEY`, `ALLOWED_HOSTS=['*']`, `CORS_ALLOW_ALL_ORIGINS`, Keycloak `start-dev` and plain HTTP are how the stack is deployed today.
