#!/usr/bin/env bash
set -euo pipefail

readonly WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly MODEL_DIR="${WORKSPACE_ROOT}/monai-apps/radiology/model"
readonly MODEL_PATH="${MODEL_DIR}/deeplab_lesion_segmentation.hdf5"
readonly MODEL_URL="https://github.com/hmgill/BigEye/raw/refs/heads/main/bigeye/deeplab_lesion_segmentation.hdf5"
readonly MODEL_SHA256="f4c3c89a4da02b84af6cc85b4ee9cd4be35bf2c836cf230b0a6d06a3805b646b"

mkdir -p "${MODEL_DIR}"

if [[ ! -f "${MODEL_PATH}" ]] || ! echo "${MODEL_SHA256}  ${MODEL_PATH}" | sha256sum --check --status; then
  curl --fail --location --retry 3 --output "${MODEL_PATH}.tmp" "${MODEL_URL}"
  echo "${MODEL_SHA256}  ${MODEL_PATH}.tmp" | sha256sum --check
  mv "${MODEL_PATH}.tmp" "${MODEL_PATH}"
fi

echo "${MODEL_SHA256}  ${MODEL_PATH}" | sha256sum --check
echo "BigEye neovascularization model ready: ${MODEL_PATH}"
