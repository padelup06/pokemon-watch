@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura n7 : services utilises par le site Cultura (2 minutes).
echo Une fenetre de navigateur s'ouvre et change de page toute seule : ne touchez a rien.
python -m pokewatch cultura-reseau > test-cultura-reseau.txt 2>&1
type test-cultura-reseau.txt
echo.
echo Envoyez le fichier test-cultura-reseau.txt a Claude.
explorer /select,"%~dp0test-cultura-reseau.txt"
pause
