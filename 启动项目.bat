@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 第一次启动：正在安装运行环境，请稍候……
  py -m venv .venv
)
echo 正在检查运行组件……
.venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check
echo 正在打开 AI 销售数据分析助手……
.venv\Scripts\python.exe -m streamlit run app.py
pause
