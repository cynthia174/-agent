from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from evaluation.evaluator import QUESTION_BANK, run_evaluation
from src.analyzer import analyze_question, load_sales_data


ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

st.set_page_config(page_title="AI 销售数据分析助手", page_icon="📊", layout="wide")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.6rem; max-width: 1200px;}
    [data-testid="stMetric"] {background:#f7f9fc; border:1px solid #e7ebf2; padding:14px; border-radius:12px;}
    .step-card {background:#f8fafc; border-left:4px solid #2563eb; padding:10px 14px; margin:8px 0; border-radius:6px;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 AI 销售数据分析助手")
st.caption("上传数据，用普通话提问；系统会展示理解、计算、检查和生成答案的完整过程。")

with st.sidebar:
    st.header("数据与设置")
    uploaded = st.file_uploader("上传销售数据（Excel 或 CSV）", type=["xlsx", "csv"])
    default_path = ROOT / "data" / "电商销售数据.xlsx"
    api_key = st.text_input(
        "Evolink API Key（可选）",
        value=os.getenv("EVOLINK_API_KEY", ""),
        type="password",
        help="不填也能运行常见分析；填写后由 AI 帮助理解更灵活的问题。",
    )
    st.caption("Key 只在本次程序运行中使用，页面不会显示明文。")
    model = st.text_input("模型", value=os.getenv("EVOLINK_MODEL", "gpt-5.5"))
    base_url = os.getenv("EVOLINK_BASE_URL", "https://direct.evolink.ai/v1")
    simulate_first_error = st.checkbox(
        "演示一次自动纠错",
        value=False,
        help="故意让第一次分析计划使用错误字段，用来展示 Agent 如何发现错误并自动修正。",
    )
    if api_key:
        st.success("当前模式：AI 规划 + 本地真实计算")
    else:
        st.info("当前模式：本地演示模式（无需联网，也会真实计算）")

source = uploaded if uploaded else default_path
try:
    df = load_sales_data(source)
except Exception as exc:
    st.error(f"数据读取失败：{exc}")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("订单数", f"{len(df):,}")
col2.metric("日期范围", f"{df['订单日期'].min():%Y-%m-%d} 至 {df['订单日期'].max():%Y-%m-%d}")
col3.metric("总销售额", f"¥{df['销售额'].sum():,.0f}")
col4.metric("覆盖产品", f"{df['产品'].nunique()} 个")

with st.expander("查看数据样例", expanded=False):
    st.dataframe(df.head(20), use_container_width=True, hide_index=True)

examples = [
    "去年总营收是多少？",
    "哪个地区营收最高？",
    "营收最高的前三个产品是什么？",
    "哪个地区的平均折扣最高？",
    "哪个月营收最高？",
    "营收最高的前三个产品是什么？顺便画张柱状图。",
    "帮我画一下每个月营收趋势。",
    "不同地区的营收对比图。",
]
st.subheader("向数据提问")
question = st.text_input("请输入你的问题", placeholder="例如：营收最高的前三个产品是什么？")
st.caption("可以直接复制尝试：" + " ｜ ".join(examples))

if st.button("开始分析", type="primary", use_container_width=True):
    steps_box = st.container()
    shown_steps: list[dict[str, str]] = []

    def show_step(item: dict[str, str]) -> None:
        shown_steps.append(item)

    try:
        with st.spinner("正在读取问题并计算真实数据……"):
            result = analyze_question(
                df,
                question,
                chart_dir=ROOT / "charts",
                api_key=api_key,
                base_url=base_url,
                model=model,
                on_step=show_step,
                simulate_first_error=simulate_first_error,
            )
        st.subheader("分析过程")
        with steps_box:
            for item in shown_steps:
                icon = "✅" if item["status"] == "完成" else ("🛠️" if item["status"] == "已修正" else "⚠️")
                st.markdown(
                    f'<div class="step-card"><b>{icon} {item["title"]}</b><br>'
                    f'<b>它尝试：</b>{item["detail"]}<br><b>运行结果：</b>{item.get("result", "")}</div>',
                    unsafe_allow_html=True,
                )
        st.subheader("最终答案")
        if result.success:
            st.success(result.answer)
        else:
            st.warning(result.answer)
        st.info("计算依据：" + result.calculation if result.calculation else "系统未执行计算。")
        if result.table is not None:
            display = result.table.copy()
            metric_cols = [c for c in ["销售额", "成本", "利润"] if c in display.columns]
            st.dataframe(
                display.style.format({c: "¥{:,.2f}" for c in metric_cols}),
                use_container_width=True,
                hide_index=True,
            )
        if result.chart is not None:
            st.pyplot(result.chart, use_container_width=True)
            st.caption(f"图表文件已保存：{result.chart_path}")
    except Exception as exc:
        st.error(f"这次分析没有完成：{exc}")
        st.info("请换一种更明确的问法，例如：“2025年各地区销售额是多少？”")

st.divider()
st.subheader("🧪 自动评测")
st.caption(f"题库共 {len(QUESTION_BANK)} 道题，覆盖总数、排名、地区、产品、月份、客户、折扣、利润、筛选和图表。")
with st.expander("查看考试题目"):
    st.dataframe(
        pd.DataFrame(QUESTION_BANK)[["id", "type", "question"]].rename(
            columns={"id": "题号", "type": "类型", "question": "问题"}
        ),
        use_container_width=True,
        hide_index=True,
    )

if st.button("运行完整自动评测", use_container_width=True):
    try:
        with st.spinner("正在逐题提问、计算标准答案并自动判分……"):
            evaluation = run_evaluation(
                df,
                output_dir=ROOT / "evaluation" / "results",
                chart_dir=ROOT / "charts",
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
        summary = evaluation["summary"]
        st.success(
            f"评测完成：{summary['通过题数']}/{summary['总题数']} 通过，"
            f"准确率 {summary['准确率']:.1f}%"
        )
        if summary["失败题号"]:
            st.error("失败题目：" + "、".join(summary["失败题号"]))
        else:
            st.info("所有题目均通过。")
        st.dataframe(pd.DataFrame(evaluation["results"]), use_container_width=True, hide_index=True)
        st.image(evaluation["score_chart_path"], caption="本次自动评测得分")
        st.caption(f"逐题结果已保存：{evaluation['csv_path']}")
        st.caption(f"完整过程已保存：{evaluation['json_path']}")
    except Exception as exc:
        st.error(f"自动评测没有完成：{type(exc).__name__}: {exc}")
