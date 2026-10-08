@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal EnableDelayedExpansion
set PYTHONUTF8=1
:ask
if not exist bot-token.txt (
  echo Collez le jeton ^(token^) de votre bot Discord puis Entree :
  set "TOKEN="
  set /p TOKEN=
  if not defined TOKEN goto ask
  >bot-token.txt echo(!TOKEN!
)
python -m pokewatch.discord_setup
echo.
if exist webhooks-regions.txt (
  notepad webhooks-regions.txt
)
pause
