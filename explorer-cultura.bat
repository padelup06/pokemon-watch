@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Ouvrez cultura.com dans votre navigateur habituel, allez sur la fiche d'un produit Pokemon
echo VENDU EN MAGASIN (un coffret ou un display francais, pas un import Japon) et copiez son adresse.
echo.
set /p URL=Collez l'adresse ici puis Entree : 
echo.
echo Dans la fenetre qui s'ouvre : acceptez les cookies, cliquez sur la disponibilite en magasin,
echo tapez 06000, attendez la liste des magasins, puis FERMEZ la fenetre du navigateur.
python -m pokewatch explorer "%URL%" -o exploration-cultura.json
echo.
echo Envoyez le fichier exploration-cultura.json a Claude.
explorer /select,"%~dp0exploration-cultura.json"
pause
