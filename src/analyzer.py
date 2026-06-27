from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests


COLUMN_ALIASES = {
    "订单日期": ["订单日期", "日期", "下单日期", "order_date"],
    "地区": ["地区", "区域", "region"],
    "产品": ["产品", "商品", "product"],
    "产品类别": ["产品类别", "类别", "品类", "category"],
    "客户类型": ["客户类型", "客户", "customer_type"],
    "销售额": ["销售额", "营收", "收入", "revenue", "sales"],
    "成本": ["成本", "cost"],
    "折扣": ["折扣", "discount"],
    "数量": ["数量", "销量", "件数", "quantity"],
}
DIMENSIONS = ["产品类别", "客户类型", "地区", "产品"]
MAX_ATTEMPTS = 3


@dataclass
class AnalysisResult:
    question: str
    answer: str
    steps: list[dict[str, str]]
    table: pd.DataFrame | None = None
    chart: Any | None = None
    chart_path: str | None = None
    calculation: str = ""
    success: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


def load_sales_data(file_or_path: Any) -> pd.DataFrame:
    """读取销售表，统一列名和数据类型，并给出人能看懂的错误。"""
    name = str(getattr(file_or_path, "name", file_or_path)).lower()
    if name.endswith(".csv"):
        try:
            df = pd.read_csv(file_or_path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(file_or_path, encoding="gbk")
    else:
        df = pd.read_excel(file_or_path)

    rename_map: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for column in df.columns:
            if str(column).strip().lower() in [a.lower() for a in aliases]:
                rename_map[column] = canonical
                break
    df = df.rename(columns=rename_map)
    missing = [c for c in COLUMN_ALIASES if c not in df.columns]
    if missing:
        raise ValueError(f"数据表缺少这些列：{', '.join(missing)}")

    df = df[list(COLUMN_ALIASES)].copy()
    df["订单日期"] = pd.to_datetime(df["订单日期"], errors="coerce")
    for col in ["销售额", "成本", "折扣", "数量"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    invalid_dates = int(df["订单日期"].isna().sum())
    df = df.dropna(subset=["订单日期", "销售额"])
    if df.empty:
        raise ValueError("清洗后没有可分析的数据，请检查日期和销售额。")
    df.attrs["invalid_dates_removed"] = invalid_dates
    return df


def _detect_time_range(question: str, df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    years = [int(x) for x in re.findall(r"(20\d{2})", question)]
    if years:
        year = years[0]
        return df[df["订单日期"].dt.year == year], f"{year}年"
    if "去年" in question:
        latest = int(df["订单日期"].dt.year.max())
        year = latest - 1
        return df[df["订单日期"].dt.year == year], f"{year}年（按数据中最新年份的上一年）"
    if "今年" in question:
        year = int(df["订单日期"].dt.year.max())
        return df[df["订单日期"].dt.year == year], f"{year}年（数据中的最新年份）"
    return df, "全部日期"


def _detect_dimension(question: str) -> str | None:
    if any(k in question for k in ["每月", "每个月", "月度", "月份", "哪个月", "各月"]):
        return "月份"
    candidates = [(alias, dim) for dim in DIMENSIONS for alias in COLUMN_ALIASES[dim]]
    for alias, dim in sorted(candidates, key=lambda x: len(x[0]), reverse=True):
        if alias.lower() in question.lower():
            return dim
    return None


def _detect_top_n(question: str) -> int:
    chinese = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "十": 10}
    match = re.search(r"(?:前|top\s*)(\d+|[一二两三四五十])", question.lower())
    if not match:
        return 1
    token = match.group(1)
    return int(token) if token.isdigit() else chinese.get(token, 1)


def _local_plan(question: str) -> dict[str, Any]:
    q = question.lower()
    dimension = _detect_dimension(question)
    wants_chart = any(k in q for k in ["图", "趋势", "变化", "可视化"])
    if any(k in q for k in ["折扣"]):
        metric = "折扣"
    elif any(k in q for k in ["利润", "毛利"]):
        metric = "利润"
    elif any(k in q for k in ["数量", "销量", "件数"]):
        metric = "数量"
    elif "成本" in q:
        metric = "成本"
    else:
        metric = "销售额"

    aggregation = "mean" if any(k in q for k in ["平均", "均值"]) else "sum"
    if any(k in q for k in ["趋势", "变化"]) and dimension == "月份":
        intent = "trend"
    elif any(k in q for k in ["最高", "最多", "排名", "前三", "前五", "top"]):
        intent = "ranking"
        dimension = dimension or "产品"
    elif dimension and any(k in q for k in ["各", "分别", "对比", "比较", "分布", "图"]):
        intent = "breakdown"
    else:
        intent = "total"
    return {
        "intent": intent,
        "metric": metric,
        "dimension": dimension,
        "aggregation": aggregation,
        "top_n": _detect_top_n(question),
        "chart": wants_chart,
        "source": "本地演示模式",
    }


def _ask_llm_for_plan(
    question: str,
    columns: list[str],
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    prompt = f"""你只负责制定数据分析计划，不得回答数字。只能返回 JSON。
intent 只能是 total/ranking/breakdown/trend；metric 只能是 销售额/成本/数量/利润/折扣；
dimension 只能是 地区/产品/产品类别/客户类型/月份/null；aggregation 只能是 sum/mean。
格式：{{"intent":"ranking","metric":"销售额","dimension":"产品","aggregation":"sum","top_n":3,"chart":false}}
数据列：{columns}
问题：{question}"""
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=45,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise ValueError("AI 没有返回可执行的 JSON 分析计划")
    return json.loads(match.group(0))


def _validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("intent") not in {"total", "ranking", "breakdown", "trend"}:
        raise ValueError(f"不支持的分析类型：{plan.get('intent')}")
    if plan.get("metric") not in {"销售额", "成本", "数量", "利润", "折扣"}:
        raise ValueError(f"不支持的计算指标：{plan.get('metric')}")
    if plan.get("dimension") not in set(DIMENSIONS + ["月份", None]):
        raise ValueError(f"数据中不存在分组字段：{plan.get('dimension')}")
    if plan.get("aggregation", "sum") not in {"sum", "mean"}:
        raise ValueError(f"不支持的汇总方法：{plan.get('aggregation')}")
    plan["aggregation"] = plan.get("aggregation", "sum")
    plan["top_n"] = max(1, min(int(plan.get("top_n", 1)), 20))
    plan["chart"] = bool(plan.get("chart", False))
    return plan


def _plan_text(plan: dict[str, Any], time_label: str) -> str:
    op = "求平均值" if plan["aggregation"] == "mean" else "求和"
    dimension = plan.get("dimension") or "不分组"
    return (
        f"筛选{time_label}；指标是“{plan['metric']}”；按“{dimension}”处理；"
        f"计算方法是{op}；分析类型是 {plan['intent']}。"
    )


def _format_value(metric: str, value: float) -> str:
    if metric == "折扣":
        return f"{value:.2%}"
    if metric == "数量":
        return f"{value:,.0f} 件"
    return f"¥{value:,.2f}"


def _execute_plan(
    filtered: pd.DataFrame,
    plan: dict[str, Any],
    time_label: str,
) -> tuple[str, str, pd.DataFrame | None]:
    plan = _validate_plan(dict(plan))
    work = filtered.copy()
    if plan["metric"] == "利润":
        work["利润"] = work["销售额"] - work["成本"]
    if plan["dimension"] == "月份":
        work["月份"] = work["订单日期"].dt.to_period("M").astype(str)

    metric = plan["metric"]
    dimension = plan.get("dimension")
    aggregation = plan["aggregation"]
    intent = plan["intent"]

    if intent == "total":
        value = float(getattr(work[metric], aggregation)())
        if not math.isfinite(value):
            raise ValueError("计算结果不是有效数字")
        op = "平均值" if aggregation == "mean" else "合计"
        answer = f"{time_label}的{metric}{op}为 {_format_value(metric, value)}。"
        evidence = f"使用 {len(work):,} 条订单，对“{metric}”列执行{'平均值' if aggregation == 'mean' else '求和'}。"
        return answer, evidence, None

    if not dimension or dimension not in work.columns:
        raise ValueError(f"无法按“{dimension}”分组：数据里没有这个字段")
    grouped = (
        work.groupby(dimension, as_index=False)[metric]
        .agg(aggregation)
        .dropna(subset=[metric])
    )
    if grouped.empty:
        raise ValueError("分组计算后没有得到任何结果")
    if intent == "trend":
        table = grouped.sort_values(dimension).reset_index(drop=True)
        answer = f"已算出{time_label}{metric}的月度趋势，共 {len(table)} 个月。"
        evidence = f"使用 {len(work):,} 条订单，提取订单月份后按月对“{metric}”执行求和。"
    elif intent == "ranking":
        table = grouped.sort_values(metric, ascending=False).head(plan["top_n"]).reset_index(drop=True)
        best = table.iloc[0]
        answer = (
            f"{time_label}{metric}最高的{dimension}是“{best[dimension]}”，"
            f"{metric}为 {_format_value(metric, float(best[metric]))}。"
        )
        if plan["top_n"] > 1:
            answer += f"结果表展示前 {len(table)} 名。"
        evidence = (
            f"使用 {len(work):,} 条订单，按“{dimension}”分组，对“{metric}”执行"
            f"{'平均值' if aggregation == 'mean' else '求和'}，再从高到低排序。"
        )
    else:
        table = grouped.sort_values(metric, ascending=False).reset_index(drop=True)
        answer = f"已完成{time_label}不同{dimension}的{metric}对比，共 {len(table)} 组。"
        evidence = (
            f"使用 {len(work):,} 条订单，按“{dimension}”分组，对“{metric}”执行"
            f"{'平均值' if aggregation == 'mean' else '求和'}。"
        )
    if table[metric].isna().any():
        raise ValueError("结果中出现空值")
    return answer, evidence, table


def _repair_plan(question: str, failed_plan: dict[str, Any], error: Exception) -> dict[str, Any]:
    """根据错误回到可信的本地规划器，避免模型反复产生同一个坏计划。"""
    repaired = _local_plan(question)
    repaired["source"] = f"根据错误自动修正（{type(error).__name__}）"
    return repaired


def _create_chart(
    table: pd.DataFrame,
    plan: dict[str, Any],
    time_label: str,
    chart_dir: str | Path,
) -> tuple[Any, str]:
    if table is None or table.empty:
        raise ValueError("没有可用于画图的汇总数据")
    dimension = plan.get("dimension")
    metric = plan["metric"]
    if dimension not in table.columns or metric not in table.columns:
        raise ValueError("图表所需的横轴或纵轴字段不存在")

    chart_data = table if plan["intent"] == "trend" else table.head(12)
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(10, 5.6))
    if plan["intent"] == "trend" or dimension == "月份":
        ax.plot(chart_data[dimension], chart_data[metric], marker="o", linewidth=2.5, color="#2563EB")
        ax.set_title(f"{time_label}{metric}趋势")
        ax.tick_params(axis="x", rotation=35)
    else:
        ax.bar(chart_data[dimension], chart_data[metric], color="#2563EB")
        ax.set_title(f"{time_label}不同{dimension}的{metric}对比")
        ax.tick_params(axis="x", rotation=25)
    ax.set_xlabel(dimension)
    ax.set_ylabel(metric)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()

    output_dir = Path(chart_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"分析图表_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
    path = output_dir / filename
    fig.savefig(path, dpi=160, bbox_inches="tight")
    if not path.exists() or path.stat().st_size < 1000:
        plt.close(fig)
        raise RuntimeError("图片文件没有正确写入磁盘")
    return fig, str(path.resolve())


def analyze_question(
    df: pd.DataFrame,
    question: str,
    chart_dir: str | Path = "charts",
    api_key: str = "",
    base_url: str = "https://direct.evolink.ai/v1",
    model: str = "gpt-5.5",
    on_step: Callable[[dict[str, str]], None] | None = None,
    simulate_first_error: bool = False,
    max_attempts: int = MAX_ATTEMPTS,
) -> AnalysisResult:
    """有限步 Agent：规划 → 执行 → 检查 → 失败修正 → 最终回答。"""
    if not question.strip():
        raise ValueError("请先输入一个问题。")
    max_attempts = max(1, min(int(max_attempts), MAX_ATTEMPTS))
    steps: list[dict[str, str]] = []

    def add_step(action: str, detail: str, result: str, status: str = "完成") -> None:
        number = len(steps) + 1
        item = {
            "title": f"第{number}步：{action}",
            "detail": detail,
            "result": result,
            "status": status,
        }
        steps.append(item)
        if on_step:
            on_step(item)

    add_step(
        "理解问题",
        f"读取到 {len(df):,} 条订单，正在识别时间、指标、分组和是否需要图表。",
        f"数据日期为 {df['订单日期'].min():%Y-%m-%d} 至 {df['订单日期'].max():%Y-%m-%d}。",
    )
    filtered, time_label = _detect_time_range(question, df)
    if filtered.empty:
        add_step("检查数据范围", f"尝试筛选{time_label}。", f"没有找到{time_label}的数据。", "失败")
        total = len(steps) + 1
        final = f"- 答案：数据表里没有找到{time_label}的数据。\n- 依据：筛选后的订单数为 0。\n- 一共用了 {total} 步"
        add_step("给出最终答案", "停止继续计算，避免无意义重试。", final, "失败")
        return AnalysisResult(question, final, steps, success=False, calculation="筛选后的订单数为 0。")

    try:
        if api_key:
            plan = _validate_plan(_ask_llm_for_plan(question, list(df.columns), api_key, base_url, model))
            plan["source"] = f"AI 规划（{model}）"
        else:
            plan = _local_plan(question)
        add_step(
            "制定分析方法",
            f"规划来源：{plan['source']}。AI/规则只制定方法，不产生答案数字。",
            _plan_text(plan, time_label),
        )
    except Exception as exc:
        plan = _local_plan(question)
        add_step(
            "规划失败并切换演示模式",
            f"外部 AI 规划失败：{type(exc).__name__}: {exc}",
            f"已改用本地演示模式。{_plan_text(plan, time_label)}",
            "已修正",
        )

    if simulate_first_error:
        plan = dict(plan)
        plan["dimension"] = "不存在的字段"

    answer_text = ""
    evidence = ""
    result_table: pd.DataFrame | None = None
    attempts_used = 0
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        try:
            answer_text, evidence, result_table = _execute_plan(filtered, plan, time_label)
            add_step(
                f"第{attempt}次运行真实计算",
                _plan_text(plan, time_label),
                f"计算成功。得到 {1 if result_table is None else len(result_table)} 条结果；{answer_text}",
            )
            add_step(
                "检查计算结果",
                "检查结果是否为空、是否包含无效数字，并确认数字来自当前数据表。",
                f"检查通过；本次实际使用 {len(filtered):,} 条订单。",
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            add_step(
                f"第{attempt}次计算失败",
                _plan_text(plan, time_label) if all(k in plan for k in ["aggregation", "metric", "intent"]) else str(plan),
                f"{type(exc).__name__}: {exc}",
                "失败",
            )
            if attempt < max_attempts:
                old_plan = dict(plan)
                plan = _repair_plan(question, plan, exc)
                add_step(
                    "根据错误自动修正",
                    f"错误说明“{exc}”。为避免重复失败，重新识别字段和计算方法。",
                    f"旧计划：{old_plan}；新计划：{plan}",
                    "已修正",
                )

    if last_error is not None:
        total = len(steps) + 1
        final = (
            f"- 答案：在最多 {max_attempts} 次尝试后仍未完成计算。\n"
            f"- 依据：最后一次错误是 {type(last_error).__name__}: {last_error}\n"
            f"- 一共用了 {total} 步"
        )
        add_step("给出最终答案", "已达到最大尝试次数，停止以避免死循环。", final, "失败")
        return AnalysisResult(
            question, final, steps, success=False, calculation=str(last_error),
            meta={"plan": plan, "attempts": attempts_used, "max_attempts": max_attempts},
        )

    chart = None
    chart_path = None
    if plan.get("chart"):
        try:
            chart, chart_path = _create_chart(result_table, plan, time_label, chart_dir)
            add_step(
                "生成并保存图表",
                f"使用刚才真实计算出的汇总结果绘图，不重新编造数字。",
                f"PNG 图片已保存到：{chart_path}",
            )
        except Exception as exc:
            add_step(
                "第一次画图失败",
                "尝试用当前汇总结果生成 PNG。",
                f"{type(exc).__name__}: {exc}",
                "失败",
            )
            try:
                repaired = dict(plan)
                repaired["intent"] = "trend" if repaired.get("dimension") == "月份" else "breakdown"
                chart, chart_path = _create_chart(result_table, repaired, time_label, chart_dir)
                add_step(
                    "修正图表方式后重试",
                    "改用更通用的趋势图或柱状图。",
                    f"重试成功，PNG 图片已保存到：{chart_path}",
                    "已修正",
                )
            except Exception as second_exc:
                add_step(
                    "图表重试失败",
                    "已进行一次修正重试，现停止画图，保留计算答案。",
                    f"{type(second_exc).__name__}: {second_exc}",
                    "失败",
                )

    if chart_path:
        answer_text += f"\n图片保存位置：{chart_path}"
        evidence += " 图表使用同一份汇总结果生成。"
    total_steps = len(steps) + 1
    final_answer = (
        f"- 答案：{answer_text}\n"
        f"- 依据：{evidence}\n"
        f"- 一共用了 {total_steps} 步"
    )
    add_step("给出最终答案", "把计算结论、数据依据、图表位置和步骤数整理成固定格式。", final_answer)
    return AnalysisResult(
        question=question,
        answer=final_answer,
        steps=steps,
        table=result_table,
        chart=chart,
        chart_path=chart_path,
        calculation=evidence,
        meta={
            "plan": plan,
            "time_label": time_label,
            "rows_used": len(filtered),
            "attempts": attempts_used,
            "max_attempts": max_attempts,
        },
    )
