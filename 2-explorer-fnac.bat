@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Ouvrez fnac.com dans votre navigateur habituel, allez sur une fiche produit Pokemon
echo (un coffret, un display...) et copiez son adresse.
echo.
set /p URL=Collez l'adresse ici puis Entree : 
python -m pokewatch explorer "%URL%" -o exploration-fnac.json
echo.
echo Envoyez le fichier exploration-fnac.json a Claude.
explorer /select,"%~dp0exploration-fnac.json"
pause
