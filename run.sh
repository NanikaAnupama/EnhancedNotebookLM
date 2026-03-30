#!/usr/bin/env bash
# run.sh — Launch both FastAPI (Uvicorn) and Streamlit side by side.
# Binds to 0.0.0.0 for Railway / container compatibility.

set -e

echo "Starting SLC Video Pipeline…"

# Start FastAPI on port 8000 (background)
uvicorn api:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# Start Streamlit on port 8501 (background)
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
STREAMLIT_PID=$!

echo "FastAPI running on http://0.0.0.0:8000"
echo "Streamlit running on http://0.0.0.0:8501"

# Wait for either process to exit; if one dies, kill the other
trap "kill $UVICORN_PID $STREAMLIT_PID 2>/dev/null" EXIT
wait -n
exit $?
