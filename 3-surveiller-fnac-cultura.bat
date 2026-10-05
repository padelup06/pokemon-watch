@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist webhook.txt (
  echo Collez l'adresse de votre webhook Discord (la meme que sur GitHub^) puis Entree :
  set /p HOOK=
  call echo %%HOOK%%> webhook.txt
)
set /p POKEWATCH_DISCORD_WEBHOOK=<webhook.txt
echo Surveillance Fnac + Cultura en cours. Laissez cette fenetre ouverte.
echo Une fenetre de navigateur va s'ouvrir regulierement : c'est normal, ne la fermez pas.
python -m pokewatch -c config.pc.toml watch
pause
