@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cdiscount : un navigateur va s'ouvrir sur cdiscount.com (1 a 2 minutes).
echo Si Cdiscount affiche une case "Je ne suis pas un robot", cochez-la.
echo Ne fermez pas la fenetre du navigateur, elle se fermera toute seule.
echo.
python -m pokewatch test "https://www.cdiscount.com/search/10/pokemon+coffret.html" --visible --premiere-fiche > test-cdiscount.txt 2>&1
type test-cdiscount.txt
echo.
echo Envoyez le fichier test-cdiscount.txt a Claude.
explorer /select,"%~dp0test-cdiscount.txt"
pause
