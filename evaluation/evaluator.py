from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.analyzer import AnalysisResult, analyze_question


QUESTION_BANK = [
    {"id": "Q01", "type": "总数计算", "question": "2025年总营收是多少？", "check": "scalar", "metric": "销售额", "year": 2025, "aggregation": "sum"},
    {"id": "Q02", "type": "找最高或最低", "question": "哪个产品营收最低？", "check": "ranking", "metric": "销售额", "dimension": "产品", "aggregation": "sum", "order": "asc", "top_n": 1},
    {"id": "Q03", "type": "按地区比较", "question": "不同地区的营收分别是多少？", "check": "groups", "metric": "销售额", "dimension": "地区", "aggregation": "sum"},
    {"id": "Q04", "type": "按产品比较", "question": "营收最高的前三个产品是什么？", "check": "ranking", "metric": "销售额", "dimension": "产品", "aggregation": "sum", "order": "desc", "top_n": 3},
    {"id": "Q05", "type": "按月份分析", "question": "2025年每个月的营收分别是多少？", "check": "groups", "metric": "销售额", "dimension": "月份", "aggregation": "sum", "year": 2025},
    {"id": "Q06", "type": "按客户类型分析", "question": "哪个客户类型营收最高？", "check": "ranking", "metric": "销售额", "dimension": "客户类型", "aggregation": "sum", "order": "desc", "top_n": 1},
    {"id": "Q07", "type": "折扣分析", "question": "哪个地区的平均折扣最高？", "check": "ranking", "metric": "折扣", "dimension": "地区", "aggregation": "mean", "order": "desc", "top_n": 1},
    {"id": "Q08", "type": "利润分析", "question": "2025年哪个产品类别利润最高？", "check": "ranking", "metric": "利润", "dimension": "产品类别", "aggregation": "sum", "order": "desc", "top_n": 1, "year": 2025},
    {"id": "Q09", "type": "筛选条件", "question": "2024年华东地区总营收是多少？", "check": "scalar", "metric": "销售额", "year": 2024, "aggregation": "sum", "filters": {"地区": "华东"}},
    {"id": "Q10", "type": "筛选条件", "question": "2025年老客户总营收是多少？", "check": "scalar", "metric": "销售额", "year": 2025, "aggregation": "sum", "filters": {"客户类型": "老客户"}},
    {"id": "Q11", "type": "需要画图", "question": "营收最高的前三个产品是什么？顺便画张柱状图。", "check": "ranking_chart", "metric": "销售额", "dimension": "产品", "aggregation": "sum", "order": "desc", "top_n": 3},
    {"id": "Q12", "type": "需要画图", "question": "帮我画一下2025年每个月营收趋势。", "check": "groups_chart", "metric": "销售额", "dimension": "月份", "aggregation": "sum", "year": 2025},
]


def _ground_truth(df: pd.DataFrame, case: dict[str, Any]) -> pd.Series | float:
    work = df.copy()
    if case.get("year"):
        work = work[work["订单日期"].dt.year == case["year"]]
    for field, value in case.get("filters", {}).items():
        work = work[work[field] == value]
    metric = case["metric"]
    if metric == "利润":
        work["利润"] = work["销售额"] - work["成本"]
    dimension = case.get("dimension")
    if dimension == "月份":
        work["月份"] = work["订单日期"].dt.to_period("M").astype(str)
    aggregation = case["aggregation"]
    if not dimension:
        return float(getattr(work[metric], aggregation)())
    grouped = getattr(work.groupby(dimension)[metric], aggregation)()
    ascending = case.get("order") == "asc"
    if case["check"].startswith("ranking"):
        grouped = grouped.sort_values(ascending=ascending).head(case["top_n"])
    return grouped


def _compact_expected(value: pd.Series | float) -> str:
    if isinstance(value, pd.Series):
        return json.dumps({str(k): round(float(v), 4) for k, v in value.items()}, ensure_ascii=False)
    return f"{float(value):.4f}"


def _judge(case: dict[str, Any], expected: pd.Series | float, result: AnalysisResult) -> tuple[bool, str, str]:
    if not result.success:
        return False, "Agent 返回失败", result.answer
    metric = case["metric"]
    if result.table is None or metric not in result.table.columns:
        return False, "结果表缺少待检查的数字", result.answer

    tolerance = 1e-8 if metric == "折扣" else 0.011
    if isinstance(expected, float):
        actual = float(result.table.iloc[0][metric])
        passed = abs(actual - expected) <= tolerance
        return passed, "数字在允许误差内" if passed else f"数字不一致，差值={actual - expected:.4f}", f"{actual:.4f}"

    dimension = case["dimension"]
    if dimension not in result.table.columns:
        return False, f"结果表缺少“{dimension}”列", result.answer
    actual_series = result.table.set_index(dimension)[metric]
    expected_keys = [str(x) for x in expected.index.tolist()]
    actual_keys = [str(x) for x in actual_series.index.tolist()]
    if case["check"].startswith("ranking"):
        keys_ok = actual_keys == expected_keys
    else:
        keys_ok = set(actual_keys) == set(expected_keys)
    values_ok = keys_ok and all(
        abs(float(actual_series.loc[key]) - float(expected.loc[key])) <= tolerance
        for key in expected.index
    )
    chart_ok = True
    if case["check"].endswith("_chart"):
        chart_path = Path(result.chart_path) if result.chart_path else None
        chart_ok = bool(chart_path and chart_path.exists() and chart_path.suffix.lower() == ".png" and chart_path.stat().st_size > 1000)
    passed = keys_ok and values_ok and chart_ok
    reasons = []
    if not keys_ok:
        reasons.append("分组或排名顺序不一致")
    if keys_ok and not values_ok:
        reasons.append("分组数字不一致")
    if not chart_ok:
        reasons.append("PNG 图片不存在或为空")
    success_text = "排名、数字和图片均正确" if case["check"].endswith("_chart") else "分组、排名和数字均正确"
    return passed, "；".join(reasons) if reasons else success_text, _compact_expected(actual_series)


def _save_score_chart(passed: int, total: int, output: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    accuracy = passed / total * 100 if total else 0
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.barh(["自动评测"], [accuracy], color="#2563EB", height=0.45)
    ax.barh(["自动评测"], [100 - accuracy], left=[accuracy], color="#E5E7EB", height=0.45)
    ax.text(50, 0, f"{passed}/{total} 通过 · {accuracy:.1f}%", ha="center", va="center", fontsize=20, fontweight="bold", color="#111827")
    ax.set_xlim(0, 100)
    ax.set_xlabel("准确率（%）")
    ax.set_title("AI 销售数据分析 Agent 自动评测结果")
    ax.grid(axis="x", alpha=0.15)
    fig.tight_layout()
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)


def run_evaluation(
    df: pd.DataFrame,
    output_dir: str | Path,
    chart_dir: str | Path,
    api_key: str = "",
    base_url: str = "https://direct.evolink.ai/v1",
    model: str = "gpt-5.5",
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    for case in QUESTION_BANK:
        expected = _ground_truth(df, case)
        try:
            result = analyze_question(
                df,
                case["question"],
                chart_dir=chart_dir,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            passed, reason, actual = _judge(case, expected, result)
            steps = result.steps
            chart_path = result.chart_path or ""
            answer = result.answer
        except Exception as exc:
            passed, reason, actual = False, f"{type(exc).__name__}: {exc}", ""
            steps, chart_path, answer = [], "", ""
        row = {
            "题号": case["id"],
            "类型": case["type"],
            "问题": case["question"],
            "结果": "通过" if passed else "失败",
            "判断说明": reason,
            "标准答案": _compact_expected(expected),
            "实际结果": actual,
            "步骤数": len(steps),
            "图表路径": chart_path,
        }
        rows.append(row)
        details.append({**row, "最终回答": answer, "完整步骤": steps})

    passed_count = sum(row["结果"] == "通过" for row in rows)
    total = len(rows)
    accuracy = passed_count / total * 100 if total else 0
    failed = [row["题号"] for row in rows if row["结果"] == "失败"]
    summary = {
        "评测时间": datetime.now().isoformat(timespec="seconds"),
        "总题数": total,
        "通过题数": passed_count,
        "失败题数": total - passed_count,
        "准确率": accuracy,
        "失败题号": failed,
    }

    csv_path = output_dir / f"evaluation_{timestamp}.csv"
    json_path = output_dir / f"evaluation_{timestamp}.json"
    report_path = output_dir / f"evaluation_{timestamp}.md"
    score_chart_path = output_dir / f"evaluation_{timestamp}.png"
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps({"summary": summary, "results": details}, ensure_ascii=False, indent=2), encoding="utf-8")
    table_lines = ["| 题号 | 类型 | 问题 | 结果 | 判断说明 |", "|---|---|---|---|---|"]
    table_lines.extend(
        f"| {row['题号']} | {row['类型']} | {row['问题']} | {row['结果']} | {row['判断说明']} |"
        for row in rows
    )
    table_md = "\n".join(table_lines)
    report_path.write_text(
        "# 自动评测报告\n\n"
        f"- 总题数：{total}\n- 通过：{passed_count}\n- 失败：{total - passed_count}\n"
        f"- 准确率：{accuracy:.1f}%\n- 失败题号：{', '.join(failed) if failed else '无'}\n\n"
        + table_md + "\n",
        encoding="utf-8",
    )
    _save_score_chart(passed_count, total, score_chart_path)
    shutil.copyfile(csv_path, output_dir / "latest_results.csv")
    shutil.copyfile(json_path, output_dir / "latest_results.json")
    shutil.copyfile(report_path, output_dir / "latest_report.md")
    shutil.copyfile(score_chart_path, output_dir / "latest_score.png")
    return {
        "summary": summary,
        "results": rows,
        "csv_path": str(csv_path.resolve()),
        "json_path": str(json_path.resolve()),
        "report_path": str(report_path.resolve()),
        "score_chart_path": str(score_chart_path.resolve()),
    }
