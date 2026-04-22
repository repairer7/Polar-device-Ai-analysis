import json
import os
import time
from google import genai  # 注意：这里改成了新的导入方式
from datetime import datetime, timedelta
from sleep_sync import fetch_sleep_data
from hr_sync import fetch_hr_data
from activity_sync import fetch_activity_data
from bark_push import bark_push

# --- 配置 ---
POLAR_TOKEN = os.environ.get("POLAR_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 初始化最新的 Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "models/gemini-2.5-flash"

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
# ⭐ Gemini 分析（带指数退避 retry）
# ---------------------------------------------------------
def analyze_with_gemini(health_data):
    """使用 Gemini 生成约 3.5KB 的专业健康报告（带自动重试）"""
    prompt = f"""
你是一名专业的健康管理专家。请基于以下 Polar 运动手表的 24 小时监控数据，
生成一份 **结构完整、专业、可读性强、长度控制在 3.0KB–3.8KB 之间** 的健康分析报告。

⚠️ 必须严格遵守以下要求：
1. 报告总长度控制在 **3000–3800 字节**（约 1500–2000 中文字符）。
2. 内容要专业、有解释、有建议，但避免冗长重复。
3. 保留以下完整结构（每部分保持 3–6 段落 + 适量表格）：

---

# Polar 24小时健康监测报告

## 1. 睡眠质量分析
- 用表格展示关键睡眠指标（开始时间、结束时间、时长、得分）
- 3–4 段专业解读（避免长篇扩写）
- 3–4 条可执行睡眠建议（每条不超过 20 字）

## 2. 心脏负荷分析
- 用表格展示 Avg HR / Max HR / Min HR
- 3–4 段专业解读（避免重复）
- 3–4 条心率改善建议（每条不超过 20 字）

## 3. 活动水平及建议
- 用表格展示步数、强度等关键指标
- 2–3 段专业解读
- 3–4 条活动建议（每条不超过 20 字）

## 4. 潜在健康隐患与综合建议
- 列出 2–3 条潜在隐患（每条 1–2 句话）
- 给出 4–5 条综合建议（每条不超过 20 字）

---

请确保报告内容：
- 专业但不啰嗦
- 有解释但不展开过度
- 有建议但不写成长段落
- 整体阅读体验接近“专业体检报告”

以下是原始数据：
{json.dumps(health_data, indent=2, ensure_ascii=False)}
"""

    max_retries = 5

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt
            )
            return response.text

        except Exception as e:
            err = str(e)

            # 只对 503 做重试
            if "503" in err or "UNAVAILABLE" in err:
                wait = 2 ** attempt
                print(f"⚠️ Gemini 503 服务器过载，第 {attempt+1} 次重试，等待 {wait}s...")
                time.sleep(wait)
                continue

            # 其他错误直接返回
            return f"Gemini 分析出错: {err}"

    return "Gemini 分析出错: 多次重试后仍然 503，请稍后再试。"


# ---------------------------------------------------------
# ⭐ 主流程
# ---------------------------------------------------------
def main():
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"--- 正在执行清洗与 Gemini AI 分析 (区间: 21:00 - 20:59) ---")

    # 1. 获取数据
    sleep_results = fetch_sleep_data(BASE_URL, HEADERS, today_str)
    hr_results = fetch_hr_data(BASE_URL, HEADERS, today_str, yesterday_str)
    activity_results = fetch_activity_data(BASE_URL, HEADERS, today_str, yesterday_str)

    # 2. 构建精简载荷
    health_payload = {
        "metadata": {
            "report_date": today_str,
            "range": f"{yesterday_str} 21:00 to {today_str} 20:59"
        },
        "summary": {
            "sleep": sleep_results.get("summary") if sleep_results else {},
            "heart_rate_stats": hr_results.get("stats") if hr_results else {},
            "activity_stats": activity_results.get("stats") if activity_results else {}
        }
    }

    # 3. 分析与推送
    print("正在连接 Gemini AI 进行深度分析...")
    analysis_report = analyze_with_gemini(health_payload)

    # 生成 Bark 标题
    title = f"{now.year}年{now.month}月{now.day}日健康监测分析"

    # 从环境变量读取 BARK_KEY
    bark_key = os.environ.get("BARK_KEY")

    # ⭐ 使用带 retry 的 Bark 推送
    success = bark_push_with_retry(title, analysis_report, bark_key)

    if success:
        print("Bark 推送成功！")
    else:
        print("Bark 推送失败！")


if __name__ == "__main__":
    main()
