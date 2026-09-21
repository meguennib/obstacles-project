#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

echo "========================="
echo "  Starting obstacles-project"
echo "========================="
echo "Backend: $BACKEND_DIR"
echo "Frontend: $FRONTEND_DIR"
echo ""

# Check Python
if [ -f "$BACKEND_DIR/.venv/bin/python" ]; then
  PY="$BACKEND_DIR/.venv/bin/python"
else
  PY="python3"
fi

# Check .env
if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo "[WARN] backend/.env not found, copying from .env.example"
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env" || echo "[WARN] no .env.example"
fi

if [ ! -f "$FRONTEND_DIR/.env" ]; then
  echo "[WARN] frontend/.env not found, copying from .env.example"
  cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env" 2>/dev/null || echo "VITE_API_BASE=http://localhost:8000" > "$FRONTEND_DIR/.env"
fi

# Backend check
if [ ! -f "$BACKEND_DIR/app/main.py" ]; then
  echo "[ERROR] Backend not found: $BACKEND_DIR/app/main.py"
  exit 1
fi

# Frontend check
if [ ! -f "$FRONTEND_DIR/package.json" ]; then
  echo "[ERROR] Frontend not found: $FRONTEND_DIR/package.json"
  exit 1
fi

# Install backend deps if needed
if [ ! -d "$BACKEND_DIR/.venv" ]; then
  echo "[INFO] Creating venv and installing backend deps..."
  python3 -m venv "$BACKEND_DIR/.venv"
  "$BACKEND_DIR/.venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
fi

# Install frontend deps if needed
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "[INFO] Installing frontend deps..."
  (cd "$FRONTEND_DIR" && npm install)
fi

# Start backend
echo "[INFO] Starting backend on http://localhost:8000"
( cd "$BACKEND_DIR" && "$PY" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 ) &
BACK_PID=$!

# Start frontend
echo "[INFO] Starting frontend on http://localhost:5173"
( cd "$FRONTEND_DIR" && npm run dev -- --host 0.0.0.0 --port 5173 ) &
FRONT_PID=$!

echo ""
echo "Done."
echo "API:   http://localhost:8000/docs"
echo "Front: http://localhost:5173"
echo "Health: http://localhost:8000/health"
echo ""
echo "PIDs: backend=$BACK_PID frontend=$FRONT_PID"
echo "To stop: ./stop.sh or kill $BACK_PID $FRONT_PID"
echo ""

wait
