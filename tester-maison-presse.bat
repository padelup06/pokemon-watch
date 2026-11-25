@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Maison de la Presse : un navigateur s'ouvre (1 minute). Cochez la case anti-robot si elle apparait.
python -m pokewatch test "https://www.maisondelapresse.com/les-heros-de-nos-enfants/pokemon/manufacturer-the_pokemon_company.html" --visible --premiere-fiche > test-maison-presse.txt 2>&1
type test-maison-presse.txt
echo.
echo Envoyez le fichier test-maison-presse.txt a Claude.
explorer /select,"%~dp0test-maison-presse.txt"
pause
