#!/usr/bin/env bash
echo "========================="
echo "  Stopping obstacles-project"
echo "========================="

# Kill by port
for PORT in 8000 5173; do
  echo "Checking port $PORT..."
  if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -ti :$PORT || true)
    if [ -n "$PIDS" ]; then
      echo "Stopping process on port $PORT: PID=$PIDS"
      kill -9 $PIDS || true
    fi
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k ${PORT}/tcp || true
  else
    echo "No lsof/fuser found, trying pkill..."
    pkill -f "uvicorn.*$PORT" || true
    pkill -f "vite.*$PORT" || true
  fi
done

# Docker compose down if running
if [ -f "docker-compose.yml" ] && command -v docker >/dev/null 2>&1; then
  if docker compose ps | grep -q obstacles; then
    echo "Stopping docker compose..."
    docker compose down || true
  fi
fi

echo "Done."
