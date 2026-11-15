#!/bin/bash
# Run the full Bonsai 2 27B DD test: start llama-server, run the 10 Darija
# questions + the strict TVA test, write the results.
# The test can take hours (up to 30 min per question on CPU) — it prints
# one progress line per question so you can watch it.
set -e
cd "$(dirname "$0")"

MODEL_FILE="Ternary-Bonsai-2-27B-PTQ1_0.gguf"
SERVER_BIN="llama.cpp-fork/build/bin/llama-server"
PORT=8899
PID_FILE="server.pid"
LOG_FILE="server.log"

cleanup() {
  if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
      echo "stopping server (pid $PID)..."
      kill "$PID" 2>/dev/null || true
      sleep 2
      kill -9 "$PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi
}
trap cleanup EXIT

echo "== checks =="
if [ ! -f "$MODEL_FILE" ]; then
  echo "ERROR: model file $MODEL_FILE not found. Run ./setup.sh first." >&2
  exit 1
fi
if [ ! -x "$SERVER_BIN" ]; then
  echo "ERROR: $SERVER_BIN not found. Run ./setup.sh first." >&2
  exit 1
fi
echo "model + server binary present"

echo "== starting llama-server (1 slot, 2048 ctx, port $PORT) =="
cleanup
nohup "$SERVER_BIN" \
  -m "$MODEL_FILE" \
  -c 2048 -t 4 --port "$PORT" --host 127.0.0.1 \
  -ctk q8_0 -ctv q8_0 --parallel 1 \
  --alias bonsai-2-27b \
  > "$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"
echo "server pid $(cat "$PID_FILE"), log: $LOG_FILE"

echo "== waiting for the server to be ready (model load takes a few minutes) =="
READY=0
for i in $(seq 1 120); do
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ERROR: server died during startup. Last log lines:" >&2
    tail -30 "$LOG_FILE" >&2
    exit 1
  fi
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" || echo 000)"
  if [ "$CODE" = "200" ]; then
    READY=1
    break
  fi
  sleep 5
done
if [ "$READY" -ne 1 ]; then
  echo "ERROR: server did not become ready in 10 minutes. Last log lines:" >&2
  tail -30 "$LOG_FILE" >&2
  exit 1
fi
echo "server ready"

echo "== running the test: 10 questions + strict TVA test =="
echo "Pass bar: >=8/10 correct + TVA pass + under ~10 s/question."
echo "Progress prints after every question (number, seconds, understood / SQL / result)."
python3 run-bonsai2-full.py

echo "== writing the report =="
python3 write-report.py

echo ""
echo "TEST DONE."
echo "Results: bonsai2-dd-test-results.md  and  results-bonsai2.json"
