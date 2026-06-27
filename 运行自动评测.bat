@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先双击“启动项目.bat”，完成第一次安装。
  pause
  exit /b 1
)
.venv\Scripts\python.exe run_evaluation.py
pause
