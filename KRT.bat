@echo off
chcp 65001 >nul
cd /d "%~dp0"
title KRT Terminal
if not exist ".deps_ok" (
  echo  Mudhal thadavai: packages install aagudhu, 1-2 nimisham wait pannunga...
  python -m pip install -q -r requirements.txt && echo ok> .deps_ok
)
python server.py
pause
