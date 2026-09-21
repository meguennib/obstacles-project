@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ------------------------------------------------------------
REM MyProject - Stop (Kill Backend + Frontend)
REM ------------------------------------------------------------

echo =========================
echo   Stopping MyProject...
echo =========================
echo.

REM Port 8000 (Backend)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
  echo Stopping process on port 8000: PID=%%a
  taskkill /f /pid %%a 2>nul
)

REM Port 5173 (Frontend)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173" ^| findstr "LISTENING"') do (
  echo Stopping process on port 5173: PID=%%a
  taskkill /f /pid %%a 2>nul
)

echo.
echo Done.
echo If a window is still open, close it manually (it may not be bound to those ports).
echo.
pause
exit /b 0
