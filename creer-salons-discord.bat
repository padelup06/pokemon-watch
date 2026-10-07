@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist bot-token.txt (
  echo Collez le jeton ^(token^) de votre bot Discord puis Entree :
  set /p TOKEN=
  call echo %%TOKEN%%> bot-token.txt
)
python -m pokewatch.discord_setup
echo.
if exist webhooks-regions.txt (
  notepad webhooks-regions.txt
)
pause
