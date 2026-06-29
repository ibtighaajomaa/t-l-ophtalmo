FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/opt/hf-cache
ENV HF_HUB_DOWNLOAD_TIMEOUT=120
ENV HOST=0.0.0.0
ENV PORT=8010
ENV DEVICE=auto

# System deps required by Pillow / torch / transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        libgl1 \
        libglib2.0-0 \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# Install CPU-only torch first (smaller image). For GPU, see REPORT-GENERATOR.md.
RUN pip install --no-cache-dir \
        torch==2.5.1 torchvision==0.20.1 \
        --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-create the HF cache directory (mounted as a volume in compose)
RUN mkdir -p /opt/hf-cache

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8010/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8010"]
