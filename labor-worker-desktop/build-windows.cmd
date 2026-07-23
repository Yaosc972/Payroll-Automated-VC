@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1" %*
if errorlevel 1 (
  echo.
  echo Windows x64 build failed. Review the error above.
  pause
  exit /b 1
)
echo.
echo Windows x64 build completed.
pause
