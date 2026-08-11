#!/usr/bin/env bash
set -euo pipefail

IMAGE_REVISION="9600484566f238a9ce57ea32c33567c6044e41d8"
IMAGE_SHA256="b795b6cd4c69b252c1b4f10150a347795555032501b60fd031751ed09b896712"
IMAGE_URL="https://huggingface.co/datasets/xlangai/ubuntu_osworld/resolve/${IMAGE_REVISION}/Ubuntu.qcow2.zip?download=true"

work_dir=""
source_url="$IMAGE_URL"
expected_sha256="$IMAGE_SHA256"
tos_bucket=""
tos_key="osworld-v1/Ubuntu.qcow2"
tos_endpoint=""
tosutil_bin="tosutil"
upload=false
dry_run=false
source_overridden=false
checksum_overridden=false

usage() {
  printf '%s\n' \
    "Usage: $0 --work-dir DIR [--upload --tos-bucket BUCKET] [options]" \
    "" \
    "Downloads the pinned official OSWorld v1 image, verifies SHA-256, extracts" \
    "and validates QCOW2, and optionally uploads it with tosutil checksum verification." \
    "" \
    "Options:" \
    "  --work-dir DIR       Persistent directory for the 12.3 GB archive and QCOW2" \
    "  --upload             Upload the validated QCOW2 to TOS" \
    "  --tos-bucket NAME    Existing TOS bucket in the target ECS region" \
    "  --tos-key KEY        Object key (default: osworld-v1/Ubuntu.qcow2)" \
    "  --tos-endpoint HOST  TOS endpoint used when printing the import URL" \
    "  --tosutil PATH       tosutil binary (default: tosutil from PATH)" \
    "  --source-url URL     Override only for a controlled mirror or testing" \
    "  --sha256 HEX         Required checksum for an overridden source" \
    "  --dry-run            Print the locked source and intended operations" \
    "  -h, --help           Show this help"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --work-dir) work_dir=${2:?missing directory}; shift 2 ;;
    --upload) upload=true; shift ;;
    --tos-bucket) tos_bucket=${2:?missing bucket}; shift 2 ;;
    --tos-key) tos_key=${2:?missing key}; shift 2 ;;
    --tos-endpoint) tos_endpoint=${2:?missing endpoint}; shift 2 ;;
    --tosutil) tosutil_bin=${2:?missing path}; shift 2 ;;
    --source-url) source_url=${2:?missing URL}; source_overridden=true; shift 2 ;;
    --sha256) expected_sha256=${2:?missing checksum}; checksum_overridden=true; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$work_dir" ]]; then
  printf '%s\n' "--work-dir is required; use a volume with at least 40 GiB free." >&2
  exit 2
fi
if [[ "$upload" == true && -z "$tos_bucket" ]]; then
  printf '%s\n' "--tos-bucket is required with --upload." >&2
  exit 2
fi
if [[ "$source_overridden" == true && "$checksum_overridden" != true ]]; then
  printf '%s\n' "--sha256 is required with --source-url; never trust an unpinned mirror." >&2
  exit 2
fi
if [[ ! "$expected_sha256" =~ ^[0-9a-fA-F]{64}$ ]]; then
  printf '%s\n' "--sha256 must be exactly 64 hexadecimal characters." >&2
  exit 2
fi

archive="$work_dir/Ubuntu.qcow2.zip"
qcow="$work_dir/Ubuntu.qcow2"
region=${VOLCENGINE_REGION:-<region>}
if [[ -z "$tos_endpoint" ]]; then
  tos_endpoint="tos-${region}.volces.com"
fi

printf 'OSWorld image revision: %s\n' "$IMAGE_REVISION"
printf 'Source: %s\n' "$source_url"
printf 'Required SHA-256: %s\n' "$expected_sha256"
printf 'Work directory: %s\n' "$work_dir"

if [[ "$dry_run" == true ]]; then
  printf 'Would download to: %s\n' "$archive"
  printf 'Would validate QCOW2: %s\n' "$qcow"
  if [[ "$upload" == true ]]; then
    printf 'Would upload to: tos://%s/%s\n' "$tos_bucket" "$tos_key"
  fi
  exit 0
fi

for command in curl unzip qemu-img; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command" >&2
    exit 1
  fi
done
if [[ "$upload" == true && ! -x "$(command -v "$tosutil_bin" 2>/dev/null || true)" ]]; then
  printf 'tosutil binary not found or not executable: %s\n' "$tosutil_bin" >&2
  exit 1
fi

mkdir -p "$work_dir"
curl --fail --location --continue-at - --output "$archive" "$source_url"

if command -v sha256sum >/dev/null 2>&1; then
  actual_sha256=$(sha256sum "$archive" | awk '{print $1}')
else
  actual_sha256=$(shasum -a 256 "$archive" | awk '{print $1}')
fi
actual_sha256_lower=$(printf '%s' "$actual_sha256" | tr '[:upper:]' '[:lower:]')
expected_sha256_lower=$(printf '%s' "$expected_sha256" | tr '[:upper:]' '[:lower:]')
if [[ "$actual_sha256_lower" != "$expected_sha256_lower" ]]; then
  printf 'Checksum mismatch for %s\nexpected: %s\nactual:   %s\n' \
    "$archive" "$expected_sha256" "$actual_sha256" >&2
  exit 1
fi

if [[ ! -f "$qcow" ]]; then
  unzip -n "$archive" -d "$work_dir"
fi
if [[ ! -f "$qcow" ]]; then
  printf 'Expected extracted image not found: %s\n' "$qcow" >&2
  exit 1
fi
qemu-img info "$qcow"
qemu-img check "$qcow"

if [[ "$upload" == true ]]; then
  "$tosutil_bin" cp "$qcow" "tos://${tos_bucket}/${tos_key}" -vchecksum
  printf '\nTOS object URL for the ECS Import Image wizard:\nhttps://%s.%s/%s\n' \
    "$tos_bucket" "$tos_endpoint" "$tos_key"
fi

printf '%s\n' \
  "" \
  "Local validation succeeded." \
  "Continue with the documented ECS service-account authorization and Import Image wizard."
