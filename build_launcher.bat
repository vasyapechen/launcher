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

echo Building...
%PY% -m PyInstaller --onefile --noconsole ^
  --name "Launcher" ^
  --icon "icon.ico" ^
  --add-data "icon.ico;." ^
  --hidden-import=customtkinter ^
  --collect-all customtkinter ^
  launcher.py

if errorlevel 1 (echo BUILD FAILED & pause & exit /b 1)

if not exist "dist\games" mkdir "dist\games"

echo.
echo ============================================
echo   DONE!  dist\Launcher.exe
echo ============================================
pause
