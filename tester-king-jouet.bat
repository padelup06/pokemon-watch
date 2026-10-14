@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo King Jouet : ouvrez king-jouet.com dans votre navigateur habituel, allez sur la fiche d un
echo produit Pokemon (un coffret ou un booster), et copiez son adresse.
echo.
set "URL="
set /p URL=Collez l adresse de la fiche produit puis Entree : 
if not defined URL set "URL=https://www.king-jouet.com/jeux-jouets/jeux-cartes-collectionner/cartes-pokemon.htm"
echo.
echo Dans la fenetre qui s ouvre : acceptez les cookies, cochez la case anti-robot si elle apparait,
echo cliquez sur "Disponibilite en magasin" / "Retrait magasin", tapez 06210, attendez la liste des
echo magasins, puis FERMEZ la fenetre du navigateur.
python -m pokewatch explorer "%URL%" -o exploration-king-jouet.json
echo.
echo Envoyez le fichier exploration-king-jouet.json a Claude.
explorer /select,"%~dp0exploration-king-jouet.json"
pause
