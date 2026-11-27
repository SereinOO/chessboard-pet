@echo off
rem ============================================================
rem  Desktop-pet Gomoku launcher - double click to start.
rem  Optional arg: listening port, e.g.  start_gomoku.bat 27184
rem ============================================================
setlocal
cd /d "%~dp0"

rem -- 1) bundled portable python shipped inside "python\" folder --
if exist "python\pythonw.exe" (
    start "" "python\pythonw.exe" gomoku.py %*
    exit /b 0
)

rem -- 2) system python: prefer "py" launcher, fall back to PATH --
set CAND=
py -3 -c "import sys" >nul 2>nul && set CAND=py -3
if not defined CAND python -c "import sys" >nul 2>nul && set CAND=python
if not defined CAND goto nopython

%CAND% -c "import tkinter" >nul 2>nul || goto notk

rem -- Pillow needed for the animated pet; install once silently --
%CAND% -c "import PIL" >nul 2>nul || %CAND% -m pip install --user --quiet pillow

rem -- resolve real python dir, start pythonw.exe (no console) --
set PYDIR=
for /f "delims=" %%i in ('%CAND% -c "import sys;print(sys.executable)"') do set PYDIR=%%~dpi
set PYW=%PYDIR%pythonw.exe
if exist "%PYW%" (
    start "" "%PYW%" gomoku.py %*
) else (
    start "" /min %CAND% gomoku.py %*
)
exit /b 0

:nopython
echo [X] Python 3 not found. Install from https://www.python.org/downloads/
echo     and CHECK the box "tcl/tk and IDLE" during install.
pause
exit /b 1

:notk
echo [X] tkinter is missing in your Python. Re-install Python and
echo     include the "tcl/tk and IDLE" component.
pause
exit /b 1
