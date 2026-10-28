@echo off
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
echo Backend running at http://localhost:8000/ping

REM 不带 --reload 的原因（都是真问题，不是洁癖）：
REM 1) --reload 会起 reloader + worker 两个进程，SQLite 的 checkpoints.db 容易 "database is locked"
REM 2) 令牌桶限流是进程内内存的，多进程下每个进程各一份，实际限额被放大
REM 3) 跑评测时任何文件改动都会重启，把跑了一半的评测打断
REM 需要热重载时，自己临时执行：uvicorn main:app --reload
uvicorn main:app --host 127.0.0.1 --port 8000
