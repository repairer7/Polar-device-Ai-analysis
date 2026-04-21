import json
import os
from google import genai
from datetime import datetime, timedelta
from sleep_sync import fetch_sleep_data
from hr_sync import fetch_hr_data
from activity_sync import fetch_activity_data
from bark_push import bark_push

# --- 配置 (改为从环境变量获取) ---
POLAR_TOKEN = os.environ.get("POLAR_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 初始化最新的 Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "models/gemini-2.5-flash"

# ... (中间代码保持不变) ...

# 3. 分析与推送
print("正在连接 Gemini AI 进行深度分析...")
analysis_report = analyze_with_gemini(health_payload)

# 生成 Bark 标题
title = f"{now.year}年{now.month}月{now.day}日健康监测分析"

# Bark 推送 (改为从环境变量获取，若未设置 host 则使用默认值)
bark_key = os.environ.get("BARK_KEY")
bark_host = os.environ.get("BARK_HOST", "https://bark.imtsui.com")

# 注意这里需要把 bark_host 也传给 bark_push 函数
success = bark_push(title, analysis_report, bark_key, bark_host)

if success:
    print("Bark 推送成功！")
else:
    print("Bark 推送失败！")

if __name__ == "__main__":
    main()