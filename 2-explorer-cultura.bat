@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Ouvrez cultura.com dans votre navigateur habituel, allez sur une fiche produit Pokemon
echo (un coffret, un display...) et copiez son adresse.
echo.
set /p URL=Collez l'adresse ici puis Entree : 
python -m pokewatch explorer "%URL%" -o exploration-cultura.json
echo.
echo Envoyez le fichier exploration-cultura.json a Claude.
explorer /select,"%~dp0exploration-cultura.json"
pause
