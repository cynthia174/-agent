"""小白也能看懂的自动检查入口。"""
from pathlib import Path
import subprocess
import sys


root = Path(__file__).parent
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q"],
    cwd=root,
    text=True,
)
if result.returncode == 0:
    print("\n[PASS] 全部检查通过：数据读取、金额计算、排名、利润、错误处理、运行时限和图表功能正常。")
else:
    print("\n[FAIL] 有检查未通过，请查看上方提示。")
raise SystemExit(result.returncode)
