@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura n8 : le 2e catalogue de Cultura (2 minutes).
echo Une fenetre de navigateur s'ouvre et change de page toute seule : ne touchez a rien.
python -m pokewatch cultura-reseau > test-cultura-reseau.txt 2>&1
echo.
echo Envoyez le fichier test-cultura-m2.json a Claude.
explorer /select,"%~dp0test-cultura-m2.json"
pause
