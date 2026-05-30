@echo off
echo ============================================
echo   Building Launcher.exe
echo ============================================
echo.

set PY=
where py >nul 2>&1 && set PY=py
if "%PY%"=="" where python >nul 2>&1 && set PY=python
if "%PY%"=="" (echo ERROR: Python not found & pause & exit /b 1)

echo Installing dependencies...
%PY% -m pip install pyinstaller customtkinter --quiet

if exist build rmdir /s /q build >nul 2>&1
if exist dist  rmdir /s /q dist  >nul 2>&1

echo Building (onedir)...
%PY% -m PyInstaller --onedir --noconsole ^
  --name "Launcher" ^
  --icon "icon.ico" ^
  --add-data "icon.ico;." ^
  --hidden-import=customtkinter ^
  --collect-all customtkinter ^
  launcher.py

if errorlevel 1 (echo BUILD FAILED & pause & exit /b 1)

echo Packing Launcher.zip...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Launcher' -DestinationPath 'dist\Launcher.zip' -Force"

echo.
echo ============================================
echo   DONE!  dist\Launcher\  +  dist\Launcher.zip
echo ============================================
pause
