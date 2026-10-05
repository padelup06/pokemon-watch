@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Test Cultura : un navigateur va s'ouvrir et parcourir Cultura (2 a 5 minutes).
echo Ne fermez pas la fenetre du navigateur, elle se fermera toute seule.
echo.
python -m pokewatch -c config.pc.toml check > test-cultura.txt 2>&1
type test-cultura.txt
echo.
echo Envoyez le fichier test-cultura.txt a Claude.
explorer /select,"%~dp0test-cultura.txt"
pause
