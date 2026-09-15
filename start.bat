@echo off
title ArmWrestling Bot + Swarm
cd /d "%~dp0"
call venv\Scripts\activate.bat
python bot.py
pause