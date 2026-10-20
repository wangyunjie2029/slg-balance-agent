@echo off
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
echo Backend running at http://localhost:8000/ping
uvicorn main:app --reload
