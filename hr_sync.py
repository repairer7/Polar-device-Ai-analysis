import requests
from datetime import datetime, timedelta

def fetch_hr_data(base_url, headers, today_str, yesterday_str):
    """获取并处理跨天心率数据"""
    def get_raw(date_str):
        url = f"{base_url}/users/continuous-heart-rate/{date_str}"
        resp = requests.get(url, headers=headers)
        return resp.json() if resp.status_code == 200 else None

    raw_yesterday = get_raw(yesterday_str)
    raw_today = get_raw(today_str)

    combined_samples = []
    # 逻辑切片
    if raw_yesterday:
        combined_samples.extend([s for s in raw_yesterday.get('heart_rate_samples', []) if s['sample_time'] >= "21:00:00"])
    if raw_today:
        combined_samples.extend([s for s in raw_today.get('heart_rate_samples', []) if s['sample_time'] < "21:00:00"])

    # 计算统计值
    hr_values = [s['heart_rate'] for s in combined_samples]
    stats = {
        "avg": round(sum(hr_values) / len(hr_values), 1) if hr_values else 0,
        "max": max(hr_values) if hr_values else 0,
        "min": min(hr_values) if hr_values else 0,
        "count": len(hr_values)
    }

    return {
        "raw_yesterday": raw_yesterday,
        "raw_today": raw_today,
        "filtered_samples": combined_samples,
        "stats": stats
    }