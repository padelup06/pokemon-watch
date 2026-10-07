@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if not exist webhook.txt (
  echo Collez l'adresse de votre webhook Discord (la meme que sur GitHub^) puis Entree :
  set /p HOOK=
  call echo %%HOOK%%> webhook.txt
)
set /p POKEWATCH_DISCORD_WEBHOOK=<webhook.txt
if not exist webhook-06.txt (
  echo.
  echo Salon de region : collez l'adresse du webhook du salon #alertes-06 puis Entree
  echo ^(ou Entree directement pour tout recevoir dans le salon principal^) :
  set "Z06="
  set /p Z06=
  if defined Z06 (echo !Z06!> webhook-06.txt)
)
if exist webhook-06.txt (
  set /p Z06=<webhook-06.txt
  set "POKEWATCH_ZONE_WEBHOOKS=06=!Z06!"
)
echo Surveillance en cours : vos produits environ toutes les minutes, toutes les enseignes en parallèle. Laissez cette fenetre ouverte.
echo Une fenetre de navigateur (Cultura) reste reduite dans la barre des taches : ne la fermez pas.
python -m pokewatch -c config.pc.toml watch
pause
