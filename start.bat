@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist "app.py" goto missing
if not exist "index.html" goto missing
if not exist "requirements.txt" goto missing
py -3 --version >nul 2>&1
if not errorlevel 1 goto use_py
python --version >nul 2>&1
if not errorlevel 1 goto use_python
echo Python 3 was not found. Install Python 3 from https://www.python.org/downloads/
goto failed
:use_py
set "PYTHON_CMD=py -3"
goto setup
:use_python
set "PYTHON_CMD=python"
:setup
if exist ".venv\Scripts\python.exe" goto deps
%PYTHON_CMD% -m venv .venv
if errorlevel 1 goto failed
:deps
".venv\Scripts\python.exe" -c "import playwright.sync_api, tzdata, tkinter, cryptography, PIL" >nul 2>&1
if not errorlevel 1 goto run
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto failed
:run
if not exist "app-icon.ico" ".venv\Scripts\python.exe" make_icon.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import tkinter"
if errorlevel 1 goto tk_missing
echo Opening the local dashboard. Keep this console open.
".venv\Scripts\python.exe" "app.py"
if errorlevel 1 goto failed
exit /b 0
:tk_missing
echo Python needs Tcl/Tk. Modify the Python installation from python.org and enable Tcl/Tk.
goto failed
:missing
echo Extract ALL files from the ZIP into one folder before running start.bat.
:failed
echo Startup failed. Read the error above. Python 3 and a compatible installed browser are required.
pause
exit /b 1
