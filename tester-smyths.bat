@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Smyths Toys : un navigateur s'ouvre sur smythstoys.com (1 minute). Ne le fermez pas.
python -m pokewatch test "https://www.smythstoys.com/fr/fr-fr/jouets/jeux-de-societe-et-puzzles/cartes-a-collectionner/cartes-pokemon/pokemon-lot-6-boosters-ev03-5-ecarlate-et-violet/p/228035" --visible > test-smyths.txt 2>&1
type test-smyths.txt
echo.
echo Envoyez le fichier test-smyths.txt a Claude.
explorer /select,"%~dp0test-smyths.txt"
pause
