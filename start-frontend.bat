@echo off
cd /d "%~dp0frontend"
echo Frontend running at http://localhost:3000
call npm run dev
