#!/usr/bin/env bash
set -euo pipefail

BIGEYE_COMMIT="c09dbc164507872eb7c8b7f57c91b7ba4fdd289f"
BIGEYE_SHA256="f4c3c89a4da02b84af6cc85b4ee9cd4be35bf2c836cf230b0a6d06a3805b646b"
BIGEYE_URL="https://media.githubusercontent.com/media/Janga-Lab/BigEye/${BIGEYE_COMMIT}/bigeye/deeplab_lesion_segmentation.hdf5"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINATION_DIR="${BIGEYE_DESTINATION_DIR:-${PROJECT_ROOT}/monai-label/models/bigeye}"
DESTINATION="${DESTINATION_DIR}/deeplab_lesion_segmentation.hdf5"

mkdir -p "${DESTINATION_DIR}"
TEMP_FILE="$(mktemp "${DESTINATION}.download.XXXXXX")"
trap 'rm -f "${TEMP_FILE}"' EXIT

curl --fail --location --retry 3 --output "${TEMP_FILE}" "${BIGEYE_URL}"
printf '%s  %s\n' "${BIGEYE_SHA256}" "${TEMP_FILE}" | sha256sum --check --status || {
  echo "BigEye checkpoint SHA-256 verification failed" >&2
  exit 1
}
mv "${TEMP_FILE}" "${DESTINATION}"
trap - EXIT
echo "BigEye checkpoint installed at ${DESTINATION}"
