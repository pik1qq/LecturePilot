@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
py -3 --version >nul 2>&1
if not errorlevel 1 goto py_found
python --version >nul 2>&1
if not errorlevel 1 goto python_found
echo Python 3.10+ is required on the BUILD computer only.
echo Get it from https://www.python.org/downloads/
goto failed
:py_found
set "PYTHON_CMD=py -3"
goto build_env
:python_found
set "PYTHON_CMD=python"
:build_env
if exist ".build-venv\Scripts\python.exe" goto install
%PYTHON_CMD% -m venv .build-venv
if errorlevel 1 goto failed
:install
".build-venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -c "import tkinter"
if errorlevel 1 goto tk_missing
".build-venv\Scripts\python.exe" make_icon.py
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name LecturePilot --version-file "version_info.txt" --icon "app-icon.ico" --collect-all playwright --collect-all tzdata --add-data "update_public_key.txt;." --add-data "index.html;." --add-data "visibility.js;." --add-data "tab_audio.js;." --add-data "app-icon.png;." --add-data "app-icon.ico;." --add-data "app-icon.svg;." --add-data "app-icon-dark.png;." --add-data "app-icon-dark.ico;." --add-data "app-icon-dark.svg;." app.py
if errorlevel 1 goto failed
echo.
echo Built: dist\LecturePilot.exe
echo Test the EXE on this Windows computer before sharing it.
echo Share ONLY dist\LecturePilot.exe, never the user data folder.
explorer.exe "dist"
pause
exit /b 0
:tk_missing
echo If the error above mentions tkinter, install Python from python.org with Tcl/Tk enabled.
:failed
echo Build failed. Read the FIRST error above and report it.
pause
exit /b 1
