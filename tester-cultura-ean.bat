@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura : recherche du Mini Tin 30e par son code-barres dans le systeme de Cultura.
echo Un navigateur va s'ouvrir sur cultura.com (1 minute). Ne le fermez pas.
echo.
python -m pokewatch cultura-ean 0196214146297 --visible > test-cultura-ean.txt 2>&1
type test-cultura-ean.txt
echo.
echo Envoyez le fichier test-cultura-ean.txt a Claude.
explorer /select,"%~dp0test-cultura-ean.txt"
pause
