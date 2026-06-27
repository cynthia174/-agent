"""运行完整题库，并保存每一道题的判断结果。"""
from pathlib import Path
import sys

from evaluation.evaluator import run_evaluation
from src.analyzer import load_sales_data


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
data = load_sales_data(ROOT / "data" / "电商销售数据.xlsx")
report = run_evaluation(
    data,
    output_dir=ROOT / "evaluation" / "results",
    chart_dir=ROOT / "charts",
)
summary = report["summary"]
print(f"评测完成：{summary['通过题数']}/{summary['总题数']} 通过，准确率 {summary['准确率']:.1f}%")
if summary["失败题号"]:
    print("失败题目：" + "、".join(summary["失败题号"]))
else:
    print("失败题目：无")
print("详细报告：" + report["report_path"])
print("逐题 CSV：" + report["csv_path"])
print("完整 JSON：" + report["json_path"])
