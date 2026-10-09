@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "MAG="
set /p MAG=Nom du magasin (ex. Mandelieu, Nice, Grasse) puis Entree : 
if not defined MAG set MAG=Mandelieu
python -m pokewatch -c config.pc.toml magasin "%MAG%"
echo.
pause
