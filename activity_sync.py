import requests
from datetime import datetime, timedelta

def fetch_activity_data(base_url, headers, today_str, yesterday_str):
    """获取并处理跨天活动样本数据（严格按时间区间过滤）"""

    def get_raw(date_str):
        url = f"{base_url}/users/activities/samples"
        params = {"date": date_str}
        resp = requests.get(url, headers=headers, params=params)
        return resp.json() if resp.status_code == 200 else None

    raw_yesterday = get_raw(yesterday_str)
    raw_today = get_raw(today_str)

    # 构造真正的 datetime 边界
    start_dt = datetime.fromisoformat(f"{yesterday_str}T21:00:00")
    end_dt   = datetime.fromisoformat(f"{today_str}T20:59:59")

    combined_samples = []

    def filter_samples(raw):
        if raw and isinstance(raw, list):
            for entry in raw:
                if "steps" in entry and "samples" in entry["steps"]:
                    for s in entry["steps"]["samples"]:
                        ts = s.get("timestamp")
                        if not ts:
                            continue
                        # Polar 返回的 timestamp 可能带 Z，需要处理
                        ts = ts.replace("Z", "")
                        ts_dt = datetime.fromisoformat(ts)

                        # 严格时间区间过滤
                        if start_dt <= ts_dt <= end_dt:
                            combined_samples.append(s)

    filter_samples(raw_yesterday)
    filter_samples(raw_today)

    # 统计
    step_values = [s['steps'] for s in combined_samples]
    stats = {
        "total_steps": sum(step_values),
        "max_step_intensity": max(step_values) if step_values else 0,
        "count": len(combined_samples)
    }

    return {
        "raw_yesterday": raw_yesterday,
        "raw_today": raw_today,
        "filtered_samples": combined_samples,
        "stats": stats
    }
