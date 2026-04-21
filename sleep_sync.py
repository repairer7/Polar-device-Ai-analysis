import requests
from datetime import datetime

def fetch_sleep_data(base_url, headers, target_date):
    """获取并处理睡眠数据"""
    url = f"{base_url}/users/sleep"
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            raw_data = resp.json()
            # 查找目标日期记录
            nights = raw_data.get('nights', [])
            target_night = next((n for n in nights if n['date'] == target_date), None)
            
            return {
                "raw_all": raw_data,
                "summary": {
                    "has_data": target_night is not None,
                    "start_time": target_night['sleep_start_time'] if target_night else None,
                    "end_time": target_night['sleep_end_time'] if target_night else None,
                    "score": target_night['sleep_score'] if target_night else None
                }
            }
        return {"raw_all": None, "summary": {"has_data": False}}
    except Exception as e:
        print(f"睡眠数据获取失败: {e}")
        return None