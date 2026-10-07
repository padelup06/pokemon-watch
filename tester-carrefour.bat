@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Test Carrefour : un navigateur va s'ouvrir sur carrefour.fr (1 a 2 minutes).
echo Si Carrefour affiche une case "Je ne suis pas un robot", cochez-la.
echo Ne fermez pas la fenetre du navigateur, elle se fermera toute seule.
echo.
(
python -m pokewatch test "https://www.carrefour.fr/s?q=pokemon%%20coffret" --visible
echo.
python -m pokewatch test "https://www.carrefour.fr/p/coffret-pokemon-collection-illustration-victini-asmodee-0196214112612" --visible
) > test-carrefour.txt 2>&1
type test-carrefour.txt
echo.
echo Envoyez le fichier test-carrefour.txt a Claude.
explorer /select,"%~dp0test-carrefour.txt"
pause
