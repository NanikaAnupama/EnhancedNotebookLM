#!/usr/bin/env bash
# run.sh — Launch FastAPI and/or Streamlit.
# On Railway, set SERVICE_MODE=fastapi or SERVICE_MODE=streamlit
# so each service only starts ONE process on $PORT.
# Locally (no SERVICE_MODE), both are started side by side.

set -e

echo "Starting SLC Video Pipeline…"

if [ "$SERVICE_MODE" = "fastapi" ]; then
    # ── Railway: FastAPI only ────────────────────────────────────────
    PORT="${PORT:-8000}"
    echo "FastAPI-only mode on port $PORT"
    exec uvicorn api:app --host 0.0.0.0 --port "$PORT"

elif [ "$SERVICE_MODE" = "streamlit" ]; then
    # ── Railway: Streamlit only ──────────────────────────────────────
    PORT="${PORT:-8501}"
    echo "Streamlit-only mode on port $PORT"
    exec streamlit run app.py --server.port "$PORT" --server.address 0.0.0.0 --server.headless true

else
    # ── Local dev: both side by side ─────────────────────────────────
    uvicorn api:app --host 0.0.0.0 --port 8000 &
    UVICORN_PID=$!

    streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
    STREAMLIT_PID=$!

    echo "FastAPI running on http://0.0.0.0:8000"
    echo "Streamlit running on http://0.0.0.0:8501"

    trap "kill $UVICORN_PID $STREAMLIT_PID 2>/dev/null" EXIT
    wait -n
    exit $?
fi
