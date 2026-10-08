@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo === Installation de Pokemon Watch ===
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python n'est pas installe.
  echo Installez-le depuis https://www.python.org/downloads/
  echo IMPORTANT : cochez la case "Add Python to PATH" pendant l'installation.
  echo Puis relancez ce fichier.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
python -m pip install --upgrade playwright
python -m playwright install chromium
echo.
echo === Installation terminee ===
pause
