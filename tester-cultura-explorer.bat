@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura n3 : comment trouver les produits Pokemon chez Cultura (1 a 2 minutes).
echo Le navigateur s'ouvre reduit dans la barre des taches : ne le fermez pas.
echo.
python -m pokewatch cultura-explorer --visible > test-cultura-explorer.txt 2>&1
type test-cultura-explorer.txt
echo.
echo Envoyez le fichier test-cultura-explorer.txt a Claude.
explorer /select,"%~dp0test-cultura-explorer.txt"
pause
