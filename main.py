import json
import os
import re
import time
from datetime import datetime, timedelta
from openai import OpenAI

from activity_sync import fetch_activity_data
from bark_push import bark_push
from hr_sync import fetch_hr_data
from loop_extras_sync import (
    BJT,
    fetch_biosensing_data,
    fetch_cardio_load_data,
    fetch_exercises_data,
    fetch_physical_info,
    fetch_sleepwise_data,
)
from nightly_recharge import fetch_nightly_recharge
from sleep_sync import fetch_sleep_data


# --- 配置 ---
POLAR_TOKEN = os.environ.get("POLAR_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")
MODEL_ID = "cn:deepseek-v4.1-flash"

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {POLAR_TOKEN}",
}
BASE_URL = "https://www.polaraccesslink.com/v3"


def _get_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY
    base_url = os.environ.get("OPENAI_BASE_URL") or OPENAI_BASE_URL
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _normalize_bark_text(text: str) -> str:
    """清理模型偶发输出的 Markdown 符号与多余空行，确保 Bark 手机端紧凑展示。"""
    if not text:
        return ""
    cleaned_lines = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        # 去除 Markdown 标题前缀与加粗标记
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[-*•]\s+", "", line)
        line = line.replace("**", "")
        cleaned_lines.append(line)
    normalized = "\n".join(cleaned_lines)
    # 最多保留章节间单空行
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


# ---------------------------------------------------------
# ⭐ Bark 推送重试包装函数（指数退避）
# ---------------------------------------------------------
def bark_push_with_retry(title, body, bark_key, max_retries=5):
    for attempt in range(max_retries):
        success = bark_push(title, body, bark_key)
        if success:
            return True

        wait = 2 ** attempt
        print(f"⚠️ Bark 推送失败，第 {attempt+1} 次重试，等待 {wait}s...")
        time.sleep(wait)

    return False


# ---------------------------------------------------------
# ⭐ OpenAI 分析（带指数退避 retry）
# ---------------------------------------------------------
def analyze_with_openai(health_data):
    """使用 OpenAI 生成 Polar Loop 全维度精简健康报告（纯文本，适合 Bark 阅读）"""

    prompt = f"""
你是一名专业的健康管理与运动生理学专家。请基于以下 Polar Loop 健康手环的 24 小时多维监测数据，
生成一份结构清晰、专业深入、精简紧凑、适合手机 Bark 通知阅读的中文健康分析报告。

请严格遵守以下排版与长度要求：
1. 全文使用纯文本，严禁使用 *, #, **, ` 等任何 Markdown 符号，也不要用 "- " 或 "1. " 作为行首列表符。
2. 整体排版必须紧凑：绝不要在每行之间加空行！仅在以下 4 个大章节之间保留 1 个空行，章节内部所有指标、解读和建议必须逐行紧密相连。
3. 所有数据指标必须纵向展示，例如：
   指标名称：值
4. 全篇总字数严格控制在 450 至 650 字之间，信息密度高、不废话，确保 Bark 通知一屏半内完整可读。
5. 心率分析必须参考 heart_rate_analysis 中的分段统计、夜间最低心率恢复位置(sleep_hr_dynamics)及异常阶段列表(anomalies)：
   必须明确区分“静息/非活动期异常偏高、睡眠期心率偏高、非活动心率骤变”与“正常走动或运动引起的心率升高”，严禁将日常步行/运动高心率误判为静息异常。若无异常时段，请明确写明无静息或睡眠异常段。
6. 若某项可选数据(has_data 为 false)未同步到，请在对应指标简写“暂无数据”，不要编造数字。

----------------------------------------
请严格按以下 4 个大章节输出：

睡眠与夜间恢复分析
纵向展示：睡眠起止与总时长、深睡与REM时长及占比、睡眠得分与连续性、HRV与呼吸率、ANS与恢复状态、夜间皮肤温度及基线偏离
给出两条专业解读（每条不超过28字）
给出两条改善建议（每条不超过22字）

心率动态与异常阶段深度分析
纵向展示：全天均值/最高/最低（附个人静息基准）、睡眠均值与日间均值对比、夜间最低心率时刻及恢复评价、异常或高波动时段明细（精确到HH:MM-HH:MM及状态性质）
针对心率波动与异常时段成因（压力、交感兴奋、睡前负荷、恢复延迟或正常活动等）给出2至3条深度解读（每条不超过30字）
给出两条护心与作息建议（每条不超过22字）

日常活动与心肺负荷分析
纵向展示：总步数与距离、活动千卡与目标完成率、活跃与久坐时长（含久坐提醒时间点）、运动记录与心肺负荷状态
给出两条专业解读（每条不超过28字）
给出两条运动活动建议（每条不超过22字）

生物钟清醒度与今日综合建议
纵向展示：今日精力峰值时段与犯困低谷时段、今晚最佳入睡时间窗
给出两条潜在健康隐患预警（每条一句话）
给出两条综合行动建议（每条不超过22字）
----------------------------------------

以下是结构化监测数据：
{json.dumps(health_data, indent=2, ensure_ascii=False)}
"""

    client = _get_openai_client()
    max_retries = 5

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )
            content = response.choices[0].message.content or ""
            return _normalize_bark_text(content)

        except Exception as e:
            err = str(e)
            wait = 2 ** attempt
            print(f"⚠️ OpenAI 请求出错，第 {attempt+1} 次重试，等待 {wait}s... 错误: {err}")
            time.sleep(wait)

    return "OpenAI 分析出错: 多次重试后仍然失败，请稍后再试。"


def build_health_payload(
    today_str,
    yesterday_str,
    sleep_results,
    nightly_recharge_results,
    hr_results,
    activity_results,
    biosensing_results,
    sleepwise_results,
    cardio_load_results,
    exercises_results,
    physical_info_results,
):
    """构建精简高密度的健康数据载荷供大模型分析。"""
    return {
        "metadata": {
            "device": "Polar Loop",
            "report_date": today_str,
            "timezone": "Asia/Shanghai (UTC+8)",
            "range": f"{yesterday_str} 21:00 to {today_str} 20:59",
        },
        "summary": {
            "sleep": sleep_results.get("summary") if sleep_results else {"has_data": False},
            "nightly_recharge": nightly_recharge_results.get("summary") if nightly_recharge_results else {"has_data": False},
            "heart_rate_analysis": hr_results.get("stats") if hr_results else {"has_data": False},
            "activity_stats": activity_results.get("stats") if activity_results else {},
            "biosensing": biosensing_results.get("summary") if biosensing_results else {"has_data": False},
            "sleepwise": sleepwise_results.get("summary") if sleepwise_results else {"has_data": False},
            "cardio_load": cardio_load_results.get("summary") if cardio_load_results else {"has_data": False},
            "exercises": exercises_results.get("summary") if exercises_results else {"has_data": False},
            "physical_info": physical_info_results.get("summary") if physical_info_results else {"has_data": False},
        },
    }


# ---------------------------------------------------------
# ⭐ 主流程
# ---------------------------------------------------------
def main():
    now = datetime.now(BJT)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"--- 正在执行 Polar Loop 全维度清洗与深度分析 (北京时间区间: {yesterday_str} 21:00 - {today_str} 20:59) ---")

    # 1. 获取全维度数据
    sleep_results = fetch_sleep_data(BASE_URL, HEADERS, today_str)
    nightly_recharge_results = fetch_nightly_recharge(BASE_URL, HEADERS, today_str)
    activity_results = fetch_activity_data(BASE_URL, HEADERS, today_str, yesterday_str)
    physical_info_results = fetch_physical_info(BASE_URL, HEADERS)
    biosensing_results = fetch_biosensing_data(BASE_URL, HEADERS, today_str, yesterday_str)
    sleepwise_results = fetch_sleepwise_data(BASE_URL, HEADERS, today_str, yesterday_str)
    cardio_load_results = fetch_cardio_load_data(BASE_URL, HEADERS, today_str, yesterday_str)
    exercises_results = fetch_exercises_data(BASE_URL, HEADERS, today_str, yesterday_str)

    sleep_summary = sleep_results.get("summary") if sleep_results else {}
    physical_info_summary = physical_info_results.get("summary") if physical_info_results else {}

    # 2. 跨模态心率变化与异常阶段深度检测
    hr_results = fetch_hr_data(
        BASE_URL,
        HEADERS,
        today_str,
        yesterday_str,
        sleep_summary=sleep_summary,
        activity_results=activity_results,
        exercises_results=exercises_results,
        physical_info=physical_info_summary,
    )

    # 3. 构建载荷
    health_payload = build_health_payload(
        today_str,
        yesterday_str,
        sleep_results,
        nightly_recharge_results,
        hr_results,
        activity_results,
        biosensing_results,
        sleepwise_results,
        cardio_load_results,
        exercises_results,
        physical_info_results,
    )

    # 4. 分析与推送
    print("正在连接大模型进行深度分析...")
    analysis_report = analyze_with_openai(health_payload)
    print(f"报告生成完成（长度: {len(analysis_report)} 字符）")

    title = f"{now.year}年{now.month}月{now.day}日健康监测分析"
    bark_key = os.environ.get("BARK_KEY")

    success = bark_push_with_retry(title, analysis_report, bark_key)

    if success:
        print("Bark 推送成功！")
    else:
        print("Bark 推送失败！")


if __name__ == "__main__":
    main()
