from pathlib import Path
import time

import pandas as pd
import pytest

from src.analyzer import analyze_question, load_sales_data


ROOT = Path(__file__).parents[1]
DATA = ROOT / "data" / "电商销售数据.xlsx"


@pytest.fixture(scope="module")
def sales():
    return load_sales_data(DATA)


def test_data_schema_and_quality(sales):
    expected = {"订单日期", "地区", "产品", "产品类别", "客户类型", "销售额", "成本", "折扣", "数量"}
    assert set(sales.columns) == expected
    assert len(sales) >= 500
    assert sales["销售额"].sum() > 0
    assert sales["订单日期"].notna().all()


def test_total_revenue_is_exact(sales, tmp_path):
    result = analyze_question(sales, "2025年总营收是多少？", tmp_path)
    expected = sales.loc[sales["订单日期"].dt.year == 2025, "销售额"].sum()
    assert result.success
    assert f"{expected:,.2f}" in result.answer


def test_top_three_products_are_exact(sales, tmp_path):
    result = analyze_question(sales, "2025年营收最高的前三个产品是什么？", tmp_path)
    expected = (
        sales[sales["订单日期"].dt.year == 2025]
        .groupby("产品")["销售额"].sum()
        .sort_values(ascending=False).head(3).index.tolist()
    )
    assert result.table["产品"].tolist() == expected


def test_highest_region_is_exact(sales, tmp_path):
    result = analyze_question(sales, "哪个地区营收最高？", tmp_path)
    expected = sales.groupby("地区")["销售额"].sum().idxmax()
    assert result.table.iloc[0]["地区"] == expected


def test_monthly_trend_creates_chart(sales, tmp_path):
    result = analyze_question(sales, "帮我画一张2025年每个月营收变化图。", tmp_path)
    assert result.chart is not None
    assert Path(result.chart_path).exists()
    assert Path(result.chart_path).suffix.lower() == ".png"
    assert Path(result.chart_path).stat().st_size > 1000
    assert len(result.table) == 12


def test_profit_calculation(sales, tmp_path):
    result = analyze_question(sales, "2025年各产品类别的利润分别是多少？", tmp_path)
    expected = sales[sales["订单日期"].dt.year == 2025].assign(
        利润=lambda x: x["销售额"] - x["成本"]
    ).groupby("产品类别")["利润"].sum()
    actual = result.table.set_index("产品类别")["利润"]
    pd.testing.assert_series_equal(actual.sort_index(), expected.sort_index(), check_names=False)


def test_missing_year_is_graceful(sales, tmp_path):
    result = analyze_question(sales, "2039年总营收是多少？", tmp_path)
    assert not result.success
    assert "没有找到" in result.answer


def test_empty_question_is_rejected(sales, tmp_path):
    with pytest.raises(ValueError, match="输入一个问题"):
        analyze_question(sales, "", tmp_path)


def test_missing_columns_give_clear_error(tmp_path):
    """缺列时要明确告诉用户缺什么，不能出现难懂的底层报错。"""
    broken = tmp_path / "缺列数据.csv"
    pd.DataFrame(
        {
            "订单日期": ["2025-01-01"],
            "产品": ["测试商品"],
            "销售额": [100],
        }
    ).to_csv(broken, index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match="数据表缺少这些列"):
        load_sales_data(broken)


def test_small_calculation_runs_successfully(sales, tmp_path):
    """用一小段已知数据验证程序确实在计算，而不是只生成文字。"""
    sample = sales.head(5).copy()
    result = analyze_question(sample, "总营收是多少？", tmp_path)
    expected = sample["销售额"].sum()
    assert result.success
    assert f"{expected:,.2f}" in result.answer


def test_error_is_returned_as_readable_result(sales, tmp_path):
    """没有对应数据时返回可读错误结果，而不是抛异常让页面崩溃。"""
    result = analyze_question(sales, "2099年总营收是多少？", tmp_path)
    assert result.success is False
    assert "没有找到" in result.answer
    assert result.steps[-1]["status"] == "失败"
    assert result.steps[-1]["detail"]


def test_analysis_finishes_without_looping(sales, tmp_path):
    """普通分析应在合理时间内结束，防止自动纠错无限循环。"""
    started = time.monotonic()
    result = analyze_question(sales, "营收最高的前三个产品是什么？", tmp_path)
    elapsed = time.monotonic() - started
    assert result.success
    assert elapsed < 5, f"分析耗时 {elapsed:.2f} 秒，疑似出现重复执行"
    assert len(result.steps) <= 10, "步骤数量异常，疑似出现循环"


def test_final_answer_is_clear_and_evidence_based(sales, tmp_path):
    """最终输出必须同时具备结论、数字、计算依据和过程记录。"""
    result = analyze_question(sales, "2025年总营收是多少？", tmp_path)
    assert result.answer.strip()
    assert "2025年" in result.answer
    assert "¥" in result.answer
    assert any(char.isdigit() for char in result.answer)
    assert result.calculation.strip()
    assert "求和" in result.calculation
    assert len(result.steps) >= 5
    assert result.steps[-1]["title"].endswith("给出最终答案")
    assert "- 答案：" in result.answer
    assert "- 依据：" in result.answer
    assert "- 一共用了" in result.answer


def test_average_discount_by_region(sales, tmp_path):
    result = analyze_question(sales, "哪个地区的平均折扣最高？", tmp_path)
    expected = sales.groupby("地区")["折扣"].mean().idxmax()
    assert result.table.iloc[0]["地区"] == expected
    assert result.meta["plan"]["aggregation"] == "mean"
    assert "%" in result.answer


def test_highest_revenue_month(sales, tmp_path):
    result = analyze_question(sales, "哪个月营收最高？", tmp_path)
    expected = (
        sales.assign(月份=sales["订单日期"].dt.to_period("M").astype(str))
        .groupby("月份")["销售额"].sum()
        .idxmax()
    )
    assert result.table.iloc[0]["月份"] == expected


def test_agent_recovers_after_first_error(sales, tmp_path):
    result = analyze_question(
        sales,
        "营收最高的前三个产品是什么？",
        tmp_path,
        simulate_first_error=True,
    )
    assert result.success
    assert result.meta["attempts"] == 2
    assert any(step["status"] == "失败" for step in result.steps)
    assert any(step["status"] == "已修正" for step in result.steps)
    assert len(result.steps) <= 10
