@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura n5 : plan du site et noms exacts (1 a 5 minutes).
echo Le navigateur s'ouvre reduit dans la barre des taches : ne le fermez pas.
python -m pokewatch cultura-pistes --visible > test-cultura-pistes.txt 2>&1
type test-cultura-pistes.txt
echo.
echo Envoyez le fichier test-cultura-pistes.txt a Claude.
explorer /select,"%~dp0test-cultura-pistes.txt"
pause
