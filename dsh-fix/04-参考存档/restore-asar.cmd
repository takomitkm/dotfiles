@echo off
setlocal
set "APP=%LOCALAPPDATA%\Programs\DeepSeek Harness\resources"
powershell -NoProfile -Command "if (Get-Process 'DeepSeek Harness' -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo [!] Close DeepSeek Harness first, then run this again.
  if not "%~1"=="--no-pause" pause
  exit /b 1
)
set "FOUND="
for /f "delims=" %%f in ('dir /b /o-d "%APP%\app.asar.prepatch-*" 2^>nul') do (
  copy /Y "%APP%\%%f" "%APP%\app.asar" >nul
  echo [OK] Restored from %%f
  set "FOUND=1"
  goto done
)
for /f "delims=" %%f in ('dir /b /o-d "%APP%\app.asar.bak-*" 2^>nul') do (
  copy /Y "%APP%\%%f" "%APP%\app.asar" >nul
  echo [OK] Restored from %%f
  set "FOUND=1"
  goto done
)
:done
if not defined FOUND echo [!] No backup found under %APP%
if not "%~1"=="--no-pause" pause