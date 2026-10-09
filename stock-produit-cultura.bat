@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Stock d'une fiche Cultura dans les magasins autour d'un code postal.
set "URL="
set /p URL=Collez le lien de la fiche Cultura (Entree = Bundle 30 ans) : 
if not defined URL set "URL=https://www.cultura.com/p-pokemon-bundle-de-6-boosters-30e-anniversaire-cartes-a-collectionner-francaise-asmodee-13486056.html"
set "CP="
set /p CP=Code postal (Entree = 06210 Mandelieu) : 
if not defined CP set CP=06210
echo.
echo Le navigateur s'ouvre reduit dans la barre des taches (1 minute)...
python -m pokewatch test "%URL%" --visible --cp %CP% --rayon 15
echo.
pause
