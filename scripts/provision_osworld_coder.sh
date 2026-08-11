#!/usr/bin/env bash
set -euo pipefail

finalize=false
if [[ ${1:-} == "--finalize" ]]; then
  finalize=true
  shift
fi
if [[ $# -ne 0 ]]; then
  printf 'Usage: %s [--finalize]\n' "$0" >&2
  exit 2
fi

if [[ $(id -u) -eq 0 ]]; then
  sudo_cmd=()
else
  sudo_cmd=(sudo)
fi

apt_packages=(curl jq sqlite3 imagemagick xdotool)
python_packages=(
  openpyxl pandas python-docx pdfplumber pypdf PyPDF2 PyMuPDF odfpy
  python-pptx pygame XlsxWriter
)

"${sudo_cmd[@]}" apt-get update
"${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install \
  -y --no-install-recommends "${apt_packages[@]}"
"${sudo_cmd[@]}" /usr/bin/python3 -m pip install \
  --disable-pip-version-check "${python_packages[@]}"

/usr/bin/python3 - <<'PY'
import importlib

modules = ["openpyxl", "pandas", "docx", "pdfplumber", "pypdf", "fitz", "odf", "pptx", "xlsxwriter"]
for module in modules:
    importlib.import_module(module)
print("Coder Python dependencies: OK")
PY

for command in bash curl jq sqlite3 convert xdotool; do
  command -v "$command" >/dev/null
done

if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet osworld_server.service; then
    printf '%s\n' "OSWorld server service: active"
  else
    printf '%s\n' "OSWorld server service is not active; fix it before creating the image." >&2
    exit 1
  fi
fi

if command -v ss >/dev/null 2>&1; then
  for port in 5000 9222; do
    if ! ss -ltn | grep -Eq ":${port}[[:space:]]"; then
      printf 'Required OSWorld guest port is not listening: %s\n' "$port" >&2
      exit 1
    fi
  done
fi

if [[ "$finalize" == true ]]; then
  sensitive=$(
    find /home /root -xdev -type f \
      \( -name '.env' -o -name 'credentials.json' -o -name 'client_secret*.json' \
      -o -name 'id_rsa' -o -name 'id_ed25519' \) -print -quit 2>/dev/null || true
  )
  if [[ -n "$sensitive" ]]; then
    printf 'Refusing to finalize: remove sensitive file before imaging: %s\n' "$sensitive" >&2
    exit 1
  fi

  credential_pattern='(GEMINI_AK|GOOGLE_API_KEY|OPENAI_API_KEY|VOLCENGINE_ACCESS_KEY_ID|VOLCENGINE_SECRET_ACCESS_KEY|VOLCANO_ENGINE_ACCESS_KEY|VOLCANO_ENGINE_SECRET_KEY|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY)[[:space:]]*=|https?_proxy[[:space:]]*=[^[:space:]]*://[^/@:]+:[^/@]+@'
  sensitive_config=""
  while IFS= read -r config_file; do
    if grep -Eil "$credential_pattern" "$config_file" >/dev/null 2>&1; then
      sensitive_config=$config_file
      break
    fi
  done < <(
    find /etc/profile /etc/environment /etc/profile.d /home /root -xdev -type f \
      \( -name '*.sh' -o -name '.profile' -o -name '.bashrc' -o -name '.zshrc' \) \
      2>/dev/null || true
  )
  if [[ -n "$sensitive_config" ]]; then
    printf 'Refusing to finalize: credential assignment found in: %s\n' \
      "$sensitive_config" >&2
    exit 1
  fi

  "${sudo_cmd[@]}" find /home /root -xdev -type f \
    \( -name '.bash_history' -o -name '.zsh_history' -o -name '.python_history' \) \
    -delete 2>/dev/null || true
  "${sudo_cmd[@]}" find /tmp -maxdepth 1 -name 'gade-coder-*' -delete 2>/dev/null || true
  "${sudo_cmd[@]}" /usr/bin/python3 -m pip cache purge >/dev/null 2>&1 || true
  if command -v cloud-init >/dev/null 2>&1; then
    "${sudo_cmd[@]}" cloud-init clean --logs --machine-id
  fi
  printf '%s\n' "Guest finalization completed. Shut down the instance before creating the image."
else
  printf '%s\n' \
    "Provisioning checks passed." \
    "Review the guest for task data and credentials, then rerun with --finalize before imaging."
fi
