@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura n4 : produits Cultura autour des references des produits 30 ans (1 minute).
echo Le navigateur s'ouvre reduit dans la barre des taches : ne le fermez pas.
python -m pokewatch cultura-refs --visible > test-cultura-refs.txt 2>&1
type test-cultura-refs.txt
echo.
echo Envoyez le fichier test-cultura-refs.txt a Claude.
explorer /select,"%~dp0test-cultura-refs.txt"
pause
