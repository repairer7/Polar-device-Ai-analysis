import math
from loop_extras_sync import safe_get_json

RECHARGE_STATUS_MAP = {
    1: "极差",
    2: "较差",
    3: "受损",
    4: "尚可",
    5: "良好",
    6: "极佳",
}

ANS_STATUS_MAP = {
    1: "远低于平时",
    2: "低于平时",
    3: "平时水平",
    4: "高于平时",
    5: "远高于平时",
}


def _chronological_values(samples_dict):
    """按跨午夜夜间顺序排列 HH:MM 采样字典（18:00-23:59 在 00:00-17:59 之前）。"""
    if not isinstance(samples_dict, dict) or not samples_dict:
        return []

    def _sort_key(time_str):
        t = str(time_str)
        return (0 if t >= "18:00" else 1, t)

    values = []
    for k in sorted(samples_dict.keys(), key=_sort_key):
        v = samples_dict.get(k)
        if isinstance(v, (int, float)):
            values.append(float(v))
    return values


def _summarize_hrv_trend(hrv_samples):
    vals = _chronological_values(hrv_samples)
    if not vals:
        return {"sample_count": 0}

    mid = max(1, len(vals) // 2)
    first_half = vals[:mid]
    second_half = vals[mid:] or vals[:mid]
    first_avg = round(sum(first_half) / len(first_half), 1)
    second_avg = round(sum(second_half) / len(second_half), 1)

    diff = second_avg - first_avg
    if diff >= 5:
        trend_desc = "后半夜HRV明显回升（副交感恢复良好）"
    elif diff <= -5:
        trend_desc = "后半夜HRV呈下降趋势（恢复承压）"
    else:
        trend_desc = "整夜HRV波动平稳"

    return {
        "min": round(min(vals), 1),
        "max": round(max(vals), 1),
        "first_half_avg": first_avg,
        "second_half_avg": second_avg,
        "sample_count": len(vals),
        "trend_desc": trend_desc,
    }


def _summarize_breathing_trend(breathing_samples):
    vals = _chronological_values(breathing_samples)
    if not vals:
        return {"sample_count": 0}

    mean_val = sum(vals) / len(vals)
    variance = sum((v - mean_val) ** 2 for v in vals) / len(vals)
    return {
        "min": round(min(vals), 1),
        "max": round(max(vals), 1),
        "std": round(math.sqrt(variance), 2),
        "sample_count": len(vals),
    }


def fetch_nightly_recharge(base_url, headers, target_date):
    """获取并提炼 Nightly Recharge 数据（含 HRV 与呼吸率夜间趋势特征）。"""
    raw_data = safe_get_json(
        f"{base_url}/users/nightly-recharge/{target_date}",
        headers,
        label="nightly-recharge-date",
    )

    if not isinstance(raw_data, dict) or not raw_data.get("date"):
        list_resp = safe_get_json(
            f"{base_url}/users/nightly-recharge",
            headers,
            label="nightly-recharge-list",
        )
        if isinstance(list_resp, dict):
            recharges = list_resp.get("recharges", [])
            matched = next((r for r in recharges if r.get("date") == target_date), None)
            if matched:
                raw_data = matched

    if not isinstance(raw_data, dict) or not raw_data.get("date"):
        return {
            "raw_all": raw_data,
            "summary": {"has_data": False},
        }

    nr_status = raw_data.get("nightly_recharge_status")
    ans_status = raw_data.get("ans_charge_status")

    return {
        "raw_all": raw_data,
        "summary": {
            "has_data": True,
            "date": raw_data.get("date"),
            "heart_rate_avg": raw_data.get("heart_rate_avg"),
            "beat_to_beat_avg": raw_data.get("beat_to_beat_avg"),
            "heart_rate_variability_avg": raw_data.get("heart_rate_variability_avg"),
            "breathing_rate_avg": raw_data.get("breathing_rate_avg"),
            "nightly_recharge_status": nr_status,
            "nightly_recharge_status_cn": RECHARGE_STATUS_MAP.get(nr_status, "未知"),
            "ans_charge": raw_data.get("ans_charge"),
            "ans_charge_status": ans_status,
            "ans_charge_status_cn": ANS_STATUS_MAP.get(ans_status, "未知"),
            "hrv_trend": _summarize_hrv_trend(raw_data.get("hrv_samples")),
            "breathing_trend": _summarize_breathing_trend(raw_data.get("breathing_samples")),
        },
    }
