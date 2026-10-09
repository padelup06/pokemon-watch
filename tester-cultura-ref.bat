@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "REF="
set /p REF=Reference Cultura (Entree = 13200180) : 
if not defined REF set REF=13200180
echo Le navigateur s'ouvre reduit dans la barre des taches (1 minute)...
python -m pokewatch cultura-refs --debut %REF% --fin %REF% --visible > test-cultura-ref.txt 2>&1
type test-cultura-ref.txt
echo.
echo Envoyez le fichier test-cultura-ref.txt a Claude.
explorer /select,"%~dp0test-cultura-ref.txt"
pause
