#!/bin/bash
# Setup for the Bonsai 2 27B DD test in GitHub Codespaces.
# Machine: 4 vCPU / 8 GB RAM, no GPU, no card needed.
# Safe to re-run: every step is skipped if it is already done.
set -e
cd "$(dirname "$0")"

MODEL_URL="https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf/resolve/main/Ternary-Bonsai-2-27B-PTQ1_0.gguf"
MODEL_FILE="Ternary-Bonsai-2-27B-PTQ1_0.gguf"
MODEL_SIZE=5946648928
MODEL_SHA256="53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3"
FORK_URL="https://github.com/PrismML-Eng/llama.cpp.git"
FORK_BRANCH="prism"
FORK_DIR="llama.cpp-fork"
SERVER_BIN="$FORK_DIR/build/bin/llama-server"
CLI_BIN="$FORK_DIR/build/bin/llama-cli"

if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi

echo "== 1/5 tools =="
NEED_INSTALL=0
for bin in git curl cmake g++ make python3 pip3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "missing: $bin"
    NEED_INSTALL=1
  fi
done
if [ "$NEED_INSTALL" -eq 1 ]; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq git curl cmake build-essential python3 python3-pip
else
  echo "all build tools present"
fi

echo "== 2/5 python requests =="
if python3 -c "import requests" 2>/dev/null; then
  echo "requests already installed"
else
  pip3 install --user -q requests
  echo "requests installed"
fi

echo "== 3/5 model download (5.95 GB, resumes if interrupted) =="
MODEL_OK=0
if [ -f "$MODEL_FILE" ]; then
  SIZE_NOW="$(stat -c '%s' "$MODEL_FILE")"
  if [ "$SIZE_NOW" = "$MODEL_SIZE" ] && echo "$MODEL_SHA256  $MODEL_FILE" | sha256sum -c - >/dev/null 2>&1; then
    MODEL_OK=1
    echo "model already downloaded and verified"
  else
    echo "model file present but wrong size/checksum, re-downloading"
    rm -f "$MODEL_FILE"
  fi
fi
if [ "$MODEL_OK" -eq 0 ]; then
  curl -L -C - --retry 3 -o "$MODEL_FILE" "$MODEL_URL"
  echo "verifying size and SHA-256..."
  SIZE_NOW="$(stat -c '%s' "$MODEL_FILE")"
  if [ "$SIZE_NOW" != "$MODEL_SIZE" ]; then
    echo "ERROR: size $SIZE_NOW, expected $MODEL_SIZE" >&2
    exit 1
  fi
  echo "$MODEL_SHA256  $MODEL_FILE" | sha256sum -c -
  echo "model verified"
fi

echo "== 4/5 PrismML llama.cpp fork (branch: $FORK_BRANCH) =="
if [ -d "$FORK_DIR/.git" ]; then
  echo "fork already cloned"
else
  git clone --branch "$FORK_BRANCH" --depth 1 "$FORK_URL" "$FORK_DIR"
fi

echo "== 5/5 build llama-server + llama-cli =="
if [ -x "$SERVER_BIN" ] && [ -x "$CLI_BIN" ]; then
  echo "binaries already built"
else
  (cd "$FORK_DIR" && cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON)
  (cd "$FORK_DIR" && cmake --build build -j "$(nproc)" --target llama-server llama-cli)
  ls -la "$SERVER_BIN" "$CLI_BIN"
fi

echo ""
echo "SETUP DONE. Run the test with:  ./run-test.sh"
