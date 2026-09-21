@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ------------------------------------------------------------
REM MyProject - Startup (Backend FastAPI + Front Vite)
REM Place this file in the project root directory
REM ------------------------------------------------------------

cd /d "%~dp0"

REM --- Paths
set "BACK_DIR=%~dp0backend"
set "FRONT_DIR=%~dp0frontend"

REM --- Choose Python (prefer .venv if exists)
set "PY=python"
if exist "%BACK_DIR%\.venv\Scripts\python.exe" (
  set "PY=%BACK_DIR%\.venv\Scripts\python.exe"
)

echo.
echo =========================
echo   Starting MyProject...
echo =========================
echo Backend: %BACK_DIR%
echo Front:   %FRONT_DIR%
echo.

REM --- Backend
if not exist "%BACK_DIR%\app\main.py" (
  echo [ERROR] Backend not found: "%BACK_DIR%\app\main.py"
  pause
  exit /b 1
)

start "MyProject API (FastAPI)" cmd /k ^
  "cd /d ""%BACK_DIR%"" ^&^& ""%PY%"" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

REM --- Frontend
if not exist "%FRONT_DIR%\package.json" (
  echo [ERROR] Frontend not found: "%FRONT_DIR%\package.json"
  pause
  exit /b 1
)

REM Install node modules if missing
if not exist "%FRONT_DIR%\node_modules" (
  start "MyProject Front (npm install)" cmd /k ^
    "cd /d ""%FRONT_DIR%"" ^&^& npm install"
  echo.
  echo [INFO] node_modules missing -> npm install launched in a separate window.
  echo You can run startup.bat again after install, or run: npm run dev
  echo.
  exit /b 0
)

start "MyProject Front (Vite)" cmd /k ^
  "cd /d ""%FRONT_DIR%"" ^&^& npm run dev -- --host 0.0.0.0 --port 5173"

echo.
echo Done.
echo API:   http://localhost:8000/docs
echo Front: http://localhost:5173
echo.
exit /b 0
