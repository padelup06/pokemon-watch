@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura n6 : les differentes boutiques du catalogue Cultura (1 minute).
echo Le navigateur s'ouvre reduit dans la barre des taches : ne le fermez pas.
python -m pokewatch cultura-boutiques --visible > test-cultura-boutiques.txt 2>&1
type test-cultura-boutiques.txt
echo.
echo Envoyez le fichier test-cultura-boutiques.txt a Claude.
explorer /select,"%~dp0test-cultura-boutiques.txt"
pause
