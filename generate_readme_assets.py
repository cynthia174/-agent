"""生成 README 中展示的真实产品图表。"""
from pathlib import Path
import shutil

from src.analyzer import analyze_question, load_sales_data


ROOT = Path(__file__).parent
ASSETS = ROOT / "docs" / "images"
ASSETS.mkdir(parents=True, exist_ok=True)
data = load_sales_data(ROOT / "data" / "电商销售数据.xlsx")

examples = [
    ("营收最高的前三个产品是什么？顺便画张柱状图。", "top3_products.png"),
    ("帮我画一下2025年每个月营收趋势。", "monthly_revenue_trend.png"),
]
for question, filename in examples:
    result = analyze_question(data, question, chart_dir=ASSETS)
    if not result.success or not result.chart_path:
        raise RuntimeError(f"示例图片生成失败：{question}")
    generated = Path(result.chart_path)
    target = ASSETS / filename
    shutil.copyfile(generated, target)
    if generated != target:
        generated.unlink()

score = ROOT / "evaluation" / "results" / "latest_score.png"
if not score.exists():
    raise FileNotFoundError("请先运行 run_evaluation.py 生成评测得分图")
shutil.copyfile(score, ASSETS / "evaluation_score.png")
print("README 示例图片已生成：")
for image in sorted(ASSETS.glob("*.png")):
    print(f"- {image.name}: {image.stat().st_size:,} 字节")
