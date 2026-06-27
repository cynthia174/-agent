"""在命令行中演示三道基础问题的真实计算过程。"""
from pathlib import Path
import sys

from src.analyzer import analyze_question, load_sales_data


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "电商销售数据.xlsx"
QUESTIONS = [
    "总营收是多少？",
    "那个地区营收最高？",
    "营收最高的前三个产品是什么？",
]


def main() -> None:
    data = load_sales_data(DATA_FILE)
    print(f"成功读取销售数据：{len(data):,} 条订单")
    for number, question in enumerate(QUESTIONS, 1):
        result = analyze_question(data, question, ROOT / "charts")
        print(f"\n===== 问题 {number}：{question} =====")
        for step in result.steps:
            print(f"[{step['status']}] {step['title']}：{step['detail']}")
        print(f"最终答案：{result.answer}")
        print(f"计算依据：{result.calculation}")
        if result.table is not None:
            print(result.table.to_string(index=False))


if __name__ == "__main__":
    main()
