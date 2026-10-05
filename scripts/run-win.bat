@echo off
rem Run from the repository root so venv and app.py resolve.
cd /d "%~dp0.."
echo Starting Award Tracker...
call venv\Scripts\activate
python app.py
pause
