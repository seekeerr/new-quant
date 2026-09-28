@echo off
REM Launch the strategy tracker: dashboard + scheduled recompute.
cd /d "%~dp0"
start "strategy dashboard" cmd /k py -m strategy_live.server --port 8765
timeout /t 3 >nul
start "strategy tracker" cmd /k py -m strategy_live.track --every 21600
timeout /t 2 >nul
start http://127.0.0.1:8765
