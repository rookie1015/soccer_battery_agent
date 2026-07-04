@echo off
setlocal
cd /d "%~dp0"

set "PORT=8765"

echo.
echo ==========================================
echo  Football Lottery mobile backend
echo ==========================================
echo.
echo Keep this window open while using the phone app.
echo.

echo Phone backend address candidates:
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } | ForEach-Object { '  http://' + $_.IPAddress + ':%PORT%' }"
echo.
echo In the Android app, open Settings, paste one of the addresses above,
echo then tap "Test connection".
echo.
echo Starting backend on port %PORT% ...
echo.

python -m football_lottery_agent ui --host 0.0.0.0 --port %PORT% --no-open

echo.
echo Backend stopped. Press any key to close this window.
pause >nul
