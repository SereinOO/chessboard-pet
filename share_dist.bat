@echo off
rem ============================================================
rem  Share dist\ to colleagues over LAN (HTTP download).
rem  Double click, then send the shown URL to your colleague,
rem  e.g. http://192.168.1.100:27990/
rem  Colleague clicks the zip in the browser to download it.
rem ============================================================
setlocal
cd /d "%~dp0dist"
if not exist "*.zip" (
    echo [X] No zip found in dist\. Run make_dist.py first.
    pause
    exit /b 1
)

set LANIP=
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway -ne $null}).IPv4Address.IPAddress"') do set LANIP=%%i

set PY=
py -3 -c "import sys" >nul 2>nul && set PY=py -3
if not defined PY python -c "import sys" >nul 2>nul && set PY=python
if not defined PY (
    echo [X] Python not found.
    pause
    exit /b 1
)

echo ============================================================
echo   Share URL:  http://%LANIP%:27990/
echo   Colleague: open the URL in browser, click the zip to download.
echo   (Keep this window open while sharing. Close it to stop sharing.)
echo ============================================================
%PY% -m http.server 27990 --bind 0.0.0.0
