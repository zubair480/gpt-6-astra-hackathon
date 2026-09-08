#!/usr/bin/env bash
# Explicit provisioning phase for the PLVA private reasoning LOCAL mode.
#
# This is the ONLY place in the module that touches the network for model assets. It
# downloads the pinned GGUF named in src/plva_private_reasoning/model/manifest.json into
# models/ (kept out of git via models/.gitignore), verifies its sha256, and prints the pins.
# The runtime never downloads anything; plva-pr-local refuses to start on a checksum mismatch.
#
# Usage:
#   scripts/provision_model.sh            # download (if needed) and verify
#   scripts/provision_model.sh --check    # verify an existing file only, no network
#   MODELS_DIR=/path scripts/provision_model.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
manifest="$root/src/plva_private_reasoning/model/manifest.json"
models_dir="${MODELS_DIR:-$root/models}"
check_only=0
for arg in "$@"; do
  case "$arg" in
    --check) check_only=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 64 ;;
  esac
done

read_field() {
  python3 - "$manifest" "$1" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
value = data[sys.argv[2]]
print(value)
PY
}

model_name="$(read_field model_name)"
repo="$(read_field source_repo)"
revision="$(read_field source_revision)"
filename="$(read_field filename)"
expected_sha="$(read_field sha256)"
license="$(read_field license)"
runtime="$(read_field runtime)"
size_bytes="$(read_field size_bytes)"

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
  fi
}

target="$models_dir/$filename"
url="https://huggingface.co/$repo/resolve/$revision/$filename"

echo "[provision] model:    $model_name ($license)"
echo "[provision] source:   $repo @ $revision"
echo "[provision] file:     $filename ($size_bytes bytes)"
echo "[provision] sha256:   $expected_sha"
echo "[provision] runtime:  $runtime"
echo "[provision] target:   $target"

mkdir -p "$models_dir"
# Keep weights out of git regardless of the repository's top-level .gitignore.
printf '*\n!.gitignore\n' > "$models_dir/.gitignore"

if [[ -f "$target" ]]; then
  echo "[provision] existing file found; verifying sha256 ..."
  actual="$(sha256_file "$target")"
  if [[ "$actual" == "$expected_sha" ]]; then
    echo "[provision] OK: checksum matches the pinned manifest."
    exit 0
  fi
  echo "[provision] MISMATCH: existing file does not match the manifest." >&2
  if [[ "$check_only" == 1 ]]; then exit 1; fi
  echo "[provision] removing the mismatched file and downloading again."
  rm -f "$target"
elif [[ "$check_only" == 1 ]]; then
  echo "[provision] no model file present (check-only mode; nothing downloaded)." >&2
  exit 1
fi

echo "[provision] downloading $url"
echo "[provision] this is a $(( size_bytes / 1048576 )) MiB download; it happens only in this provisioning step."
partial="$target.part"
curl --fail --location --retry 3 --retry-delay 5 --continue-at - \
  --proto '=https' --tlsv1.2 \
  --output "$partial" "$url"

echo "[provision] verifying sha256 ..."
actual="$(sha256_file "$partial")"
if [[ "$actual" != "$expected_sha" ]]; then
  echo "[provision] FAILED: downloaded file sha256 $actual != pinned $expected_sha" >&2
  rm -f "$partial"
  exit 1
fi
mv "$partial" "$target"
chmod 0644 "$target"
echo "[provision] OK: $target verified against the pinned manifest."
echo "[provision] next: uv sync --extra local && uv run plva-pr-local --model-path '$target'"
