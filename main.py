import json
import os
import time
from openai import OpenAI
from datetime import datetime, timedelta

from sleep_sync import fetch_sleep_data
from hr_sync import fetch_hr_data
from activity_sync import fetch_activity_data
from nightly_recharge import fetch_nightly_recharge
from bark_push import bark_push


# --- 配置 ---
POLAR_TOKEN = os.environ.get("POLAR_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")

# 如果配置了自定义的 Base URL（如中转站），则传入 base_url 参数
if OPENAI_BASE_URL:
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
else:
    client = OpenAI(api_key=OPENAI_API_KEY)
MODEL_ID = "sensenova-6.8-flash-lite"

HEADERS = {
    'Accept': 'application/json',
    'Authorization': f'Bearer {POLAR_TOKEN}'
}
BASE_URL = "https://www.polaraccesslink.com/v3"


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
    """使用 OpenAI 生成精简版健康报告（纯文本，无 Markdown，无符号）"""

    prompt = f"""
你是一名专业的健康管理专家。请基于以下 Polar 运动手表的 24 小时监控数据，
生成一份结构清晰、专业、精简、适合手机阅读的健康分析报告。

请严格遵守以下要求：

1. 全文使用纯文本，不要使用 *, #, -, 1. 等任何 Markdown 或符号。
2. 整体排版必须紧凑。请绝对不要在每行内容之间加空行。仅在不同大章节之间（如“睡眠质量分析”和“心脏负荷分析”）保留一个空行，章节内部的各项指标、解读、建议必须紧密相连，不能有任何空行。
3. 所有表格内容必须纵向展示，例如：
   指标A：值
   指标B：值
   指标C：值

4. 心率数据来自日常非运动时间，不包含运动心率，请按“静息/日常活动心率”进行分析，不要按运动心率解读。

5. 每个章节只包含：
   两条专业解读（每条不超过 25 字）
   两条建议（每条不超过 20 字）

6. 报告整体尽量短，适合 Bark 推送。

----------------------------------------

睡眠质量分析
请纵向展示：开始时间、结束时间、睡眠时长、睡眠得分
然后给出两条专业解读和两条建议

Nightly Recharge（ANS + HRV + 呼吸率）
请纵向展示：HRV、呼吸率、ANS Charge、状态
然后给出两条专业解读和两条建议

心脏负荷分析（静息/日常活动心率）
请纵向展示：平均心率、最高心率、最低心率、样本数量
然后给出两条专业解读和两条建议

活动水平分析
请纵向展示：步数、活动时间、卡路里等关键指标
然后给出两条专业解读和两条建议

潜在健康隐患与综合建议
两条潜在隐患（每条一句话）
两条综合建议（每条不超过 20 字）

----------------------------------------

以下是原始数据：
{json.dumps(health_data, indent=2, ensure_ascii=False)}
"""

    max_retries = 5

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content

        except Exception as e:
            err = str(e)

            wait = 2 ** attempt
            print(f"⚠️ OpenAI 请求出错，第 {attempt+1} 次重试，等待 {wait}s... 错误: {err}")
            time.sleep(wait)

    return "OpenAI 分析出错: 多次重试后仍然失败，请稍后再试。"


# ---------------------------------------------------------
# ⭐ 主流程
# ---------------------------------------------------------
def main():
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"--- 正在执行清洗与 OpenAI 分析 (区间: 21:00 - 20:59) ---")

    # 1. 获取数据
    sleep_results = fetch_sleep_data(BASE_URL, HEADERS, today_str)
    hr_results = fetch_hr_data(BASE_URL, HEADERS, today_str, yesterday_str)
    activity_results = fetch_activity_data(BASE_URL, HEADERS, today_str, yesterday_str)

    # ⭐ Nightly Recharge（新增）
    nightly_recharge_results = fetch_nightly_recharge(BASE_URL, HEADERS, today_str)

    # 2. 构建精简载荷
    health_payload = {
        "metadata": {
            "report_date": today_str,
            "range": f"{yesterday_str} 21:00 to {today_str} 20:59"
        },
        "summary": {
            "sleep": sleep_results.get("summary") if sleep_results else {},
            "nightly_recharge": nightly_recharge_results.get("summary") if nightly_recharge_results else {},
            "heart_rate_stats": hr_results.get("stats") if hr_results else {},
            "activity_stats": activity_results.get("stats") if activity_results else {}
        }
    }

    # 3. 分析与推送
    print("正在连接 OpenAI 进行深度分析...")
    analysis_report = analyze_with_openai(health_payload)

    title = f"{now.year}年{now.month}月{now.day}日健康监测分析"
    bark_key = os.environ.get("BARK_KEY")

    success = bark_push_with_retry(title, analysis_report, bark_key)

    if success:
        print("Bark 推送成功！")
    else:
        print("Bark 推送失败！")


if __name__ == "__main__":
    main()
