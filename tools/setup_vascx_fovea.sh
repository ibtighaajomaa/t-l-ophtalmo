#!/usr/bin/env bash
set -euo pipefail

readonly REPO_URL="https://huggingface.co/Eyened/vascx"
readonly REPO_REVISION="962c83a78b8867c2d3028635e7d7d1ee07fff2be"
readonly MODEL_RELATIVE_PATH="fovea/fovea_may26.pt"
readonly MODEL_SHA256="114daf518186122cdbbae66fceeb3fd00f6411b72b99bdc81c1272e36441055a"
readonly WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly MODEL_REPO="${WORKSPACE_ROOT}/monai-label/models/vascx"
readonly MODEL_PATH="${MODEL_REPO}/${MODEL_RELATIVE_PATH}"

if ! git xet --version >/dev/null 2>&1; then
  echo "git-xet is required. See https://huggingface.co/docs/hub/xet/using-xet-storage" >&2
  exit 1
fi

git xet install >/dev/null
git lfs install >/dev/null
mkdir -p "$(dirname "${MODEL_REPO}")"

if [[ ! -d "${MODEL_REPO}/.git" ]]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone "${REPO_URL}" "${MODEL_REPO}"
fi

git -C "${MODEL_REPO}" fetch origin "${REPO_REVISION}"
git -C "${MODEL_REPO}" checkout --detach "${REPO_REVISION}"

if [[ ! -f "${MODEL_PATH}" ]] || ! echo "${MODEL_SHA256}  ${MODEL_PATH}" | sha256sum --check --status; then
  git -C "${MODEL_REPO}" lfs pull --include="${MODEL_RELATIVE_PATH}" --exclude=""
fi

echo "${MODEL_SHA256}  ${MODEL_PATH}" | sha256sum --check
echo "VascX fovea model ready: ${MODEL_PATH}"
