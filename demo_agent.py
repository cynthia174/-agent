"""一键展示 Agent 循环、自动纠错和 PNG 图表。"""
from pathlib import Path
import sys

from src.analyzer import analyze_question, load_sales_data


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
DATA = load_sales_data(ROOT / "data" / "电商销售数据.xlsx")
CASES = [
    ("去年总营收是多少？", False),
    ("营收最高的前三个产品是什么？", True),
    ("哪个地区的平均折扣最高？", False),
    ("哪个月营收最高？", False),
    ("营收最高的前三个产品是什么？顺便画张柱状图。", False),
]


for index, (question, demonstrate_repair) in enumerate(CASES, 1):
    print(f"\n{'=' * 16} 演示 {index} {'=' * 16}")
    print(f"用户问题：{question}")
    result = analyze_question(
        DATA,
        question,
        chart_dir=ROOT / "charts",
        simulate_first_error=demonstrate_repair,
    )
    for step in result.steps:
        print(f"\n{step['title']} [{step['status']}]")
        print(f"它尝试：{step['detail']}")
        print(f"运行结果：{step['result']}")
    print("\n最终固定格式：")
    print(result.answer)
    if result.chart_path:
        image = Path(result.chart_path)
        print(f"图片检查：存在={image.exists()}，大小={image.stat().st_size:,} 字节")
