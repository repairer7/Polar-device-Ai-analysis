# nightly_recharge.py
import requests
from datetime import datetime, timezone, timedelta

def fetch_nightly_recharge(base_url, headers, target_date):
    """获取并处理 Nightly Recharge 数据"""
    url = f"{base_url}/users/nightly-recharge/{target_date}"

    try:
        resp = requests.get(url, headers=headers)

        if resp.status_code == 200:
            raw_data = resp.json()

            return {
                "raw_all": raw_data,
                "summary": {
                    "has_data": True,
                    "date": raw_data.get("date"),
                    "heart_rate_avg": raw_data.get("heart_rate_avg"),
                    "beat_to_beat_avg": raw_data.get("beat_to_beat_avg"),
                    "heart_rate_variability_avg": raw_data.get("heart_rate_variability_avg"),
                    "breathing_rate_avg": raw_data.get("breathing_rate_avg"),
                    "nightly_recharge_status": raw_data.get("nightly_recharge_status"),
                    "ans_charge": raw_data.get("ans_charge"),
                    "ans_charge_status": raw_data.get("ans_charge_status"),
                    "hrv_samples": raw_data.get("hrv_samples", {}),
                    "breathing_samples": raw_data.get("breathing_samples", {})
                }
            }

        # 非 200 状态码
        return {
            "raw_all": None,
            "summary": {"has_data": False}
        }

    except Exception as e:
        print(f"Nightly Recharge 数据获取失败: {e}")
        return None
