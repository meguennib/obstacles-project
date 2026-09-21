@echo off
setlocal

echo =========================
echo   Stopping MyProject...
echo =========================
echo.

REM Kill processes listening on port 8000 (FastAPI/Uvicorn)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
  echo Stopping process on port 8000: PID=%%P
  taskkill /PID %%P /F >nul 2>&1
)

REM Kill processes listening on port 5173 (Vite)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5173 .*LISTENING"') do (
  echo Stopping process on port 5173: PID=%%P
  taskkill /PID %%P /F >nul 2>&1
)

echo.
echo Done.
echo If a window is still open, close it manually (it may not be bound to those ports).
echo.
pause
exit /b 0
