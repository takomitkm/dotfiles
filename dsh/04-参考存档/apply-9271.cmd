@echo off
setlocal
set "KIT=%~dp0"
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\python\python.exe" set "PY=%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\python\python.exe"
if not defined PY if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not defined PY (
  echo [!] Python not found. Install Python or run apply-9271.py with the bundled interpreter.
  if not "%~1"=="--no-pause" pause
  exit /b 1
)
"%PY%" "%KIT%apply-9271.py"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo [OK] Done. Restart DeepSeek Harness to activate.
if not "%RC%"=="0" echo [!] Failed with exit code %RC%.
if not "%~1"=="--no-pause" pause
exit /b %RC%