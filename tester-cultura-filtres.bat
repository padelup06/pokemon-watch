@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura n9 : filtres du catalogue Cultura (1 minute).
echo Le navigateur s'ouvre reduit dans la barre des taches : ne le fermez pas.
python -m pokewatch cultura-filtres --visible > test-cultura-filtres.txt 2>&1
type test-cultura-filtres.txt
echo.
echo Envoyez le fichier test-cultura-filtres.txt a Claude.
explorer /select,"%~dp0test-cultura-filtres.txt"
pause
