@echo off
rem ============================================================
rem  Allow LAN access for gomoku: run as Administrator.
rem  27990 = share_dist.bat HTTP download
rem  27183 = gomoku game connection
rem ============================================================
netsh advfirewall firewall delete rule name="gomoku_share_http" >nul 2>nul
netsh advfirewall firewall delete rule name="gomoku_game_27183" >nul 2>nul
netsh advfirewall firewall add rule name="gomoku_share_http" dir=in action=allow protocol=TCP localport=27990
netsh advfirewall firewall add rule name="gomoku_game_27183" dir=in action=allow protocol=TCP localport=27183
if %errorlevel%==0 (
    echo.
    echo [OK] Firewall rules added: TCP 27990 + 27183 allowed.
) else (
    echo.
    echo [X] Failed - please right-click this file and "Run as administrator".
)
pause
