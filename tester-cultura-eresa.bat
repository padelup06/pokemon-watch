@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Test Cultura n10 : le service e-reservation de Cultura (1 a 2 minutes).
echo Une fenetre de navigateur s'ouvre et change de page toute seule : ne touchez a rien.
python -m pokewatch cultura-reseau --pages https://eresa.cultura.com/ https://eresa.cultura.com/magasins https://www.cultura.com/p-mini-tin-pokemon-mega-heroisme-modeles-aleatoires-vendu-a-l-unite-12369064.html --sortie test-cultura-eresa.json > test-cultura-eresa.txt 2>&1
type test-cultura-eresa.txt
echo.
echo Envoyez les fichiers test-cultura-eresa.txt ET test-cultura-eresa.json a Claude.
explorer /select,"%~dp0test-cultura-eresa.txt"
pause
