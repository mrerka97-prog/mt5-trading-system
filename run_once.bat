@echo off
REM Forex bot: run once per day (called by Task Scheduler)
set PYTHONIOENCODING=utf-8
cd /d C:\Projects\forex-bot
call .venv\Scripts\activate.bat
python scripts\run_live.py --once >> logs\once.log 2>&1
