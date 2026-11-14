from loop_extras_sync import BJT, format_duration_hm, parse_iso_dt, safe_get_json

CONTINUITY_CLASS_MAP = {
    1: "碎片化",
    2: "较碎片化",
    3: "较连续",
    4: "连续",
    5: "非常连续",
}


def _sec_to_min(val):
    return round(val / 60, 1) if isinstance(val, (int, float)) else None


def fetch_sleep_data(base_url, headers, target_date):
    """获取并深度解析 Polar 睡眠数据（含睡眠分期、中断、连续性、三大子评分及睡眠期心率）。"""
    raw_data = safe_get_json(f"{base_url}/users/sleep", headers, label="sleep-list")
    target_night = None

    if isinstance(raw_data, dict):
        nights = raw_data.get("nights", [])
        target_night = next((n for n in nights if n.get("date") == target_date), None)

    if target_night is None:
        fallback = safe_get_json(f"{base_url}/users/sleep/{target_date}", headers, label="sleep-date")
        if isinstance(fallback, dict) and fallback.get("sleep_start_time"):
            target_night = fallback
            if raw_data is None:
                raw_data = fallback

    if not target_night:
        return {
            "raw_all": raw_data,
            "sleep_hr_samples": {},
            "summary": {"has_data": False},
        }

    light_sec = target_night.get("light_sleep") or 0
    deep_sec = target_night.get("deep_sleep") or 0
    rem_sec = target_night.get("rem_sleep") or 0
    unrec_sec = target_night.get("unrecognized_sleep_stage") or 0
    total_sleep_sec = light_sec + deep_sec + rem_sec

    start_dt = parse_iso_dt(target_night.get("sleep_start_time"), target_tz=BJT)
    end_dt = parse_iso_dt(target_night.get("sleep_end_time"), target_tz=BJT)

    # 若三期之和为 0 但有起止时间，则用时间差减总中断时间估算实际睡眠时长
    total_int_sec = target_night.get("total_interruption_duration") or 0
    if total_sleep_sec == 0 and start_dt and end_dt:
        span_sec = max(0, (end_dt - start_dt).total_seconds() - total_int_sec)
        total_sleep_sec = span_sec

    denom = light_sec + deep_sec + rem_sec
    deep_pct = round(deep_sec / denom * 100, 1) if denom > 0 else None
    rem_pct = round(rem_sec / denom * 100, 1) if denom > 0 else None
    light_pct = round(light_sec / denom * 100, 1) if denom > 0 else None

    hr_dict = target_night.get("heart_rate_samples") or {}
    hr_vals = [v for v in hr_dict.values() if isinstance(v, (int, float)) and v > 0]
    sleep_stage_hr_stats = {
        "avg": round(sum(hr_vals) / len(hr_vals), 1) if hr_vals else None,
        "min": min(hr_vals) if hr_vals else None,
        "max": max(hr_vals) if hr_vals else None,
        "count": len(hr_vals),
    }

    cont_class = target_night.get("continuity_class")
    summary = {
        "has_data": True,
        "date": target_night.get("date"),
        "start_time": start_dt.strftime("%Y-%m-%d %H:%M") if start_dt else target_night.get("sleep_start_time"),
        "end_time": end_dt.strftime("%Y-%m-%d %H:%M") if end_dt else target_night.get("sleep_end_time"),
        "score": target_night.get("sleep_score"),
        "total_sleep_min": _sec_to_min(total_sleep_sec),
        "total_sleep_duration": format_duration_hm(total_sleep_sec),
        "light_sleep_min": _sec_to_min(light_sec),
        "deep_sleep_min": _sec_to_min(deep_sec),
        "rem_sleep_min": _sec_to_min(rem_sec),
        "unrecognized_sleep_min": _sec_to_min(unrec_sec),
        "deep_sleep_pct": deep_pct,
        "rem_sleep_pct": rem_pct,
        "light_sleep_pct": light_pct,
        "total_interruption_min": _sec_to_min(total_int_sec),
        "short_interruption_min": _sec_to_min(target_night.get("short_interruption_duration")),
        "long_interruption_min": _sec_to_min(target_night.get("long_interruption_duration")),
        "sleep_cycles": target_night.get("sleep_cycles"),
        "continuity": target_night.get("continuity"),
        "continuity_class": cont_class,
        "continuity_desc": CONTINUITY_CLASS_MAP.get(cont_class, "未知"),
        "sleep_charge": target_night.get("sleep_charge"),
        "sleep_rating": target_night.get("sleep_rating"),
        "sleep_goal_min": _sec_to_min(target_night.get("sleep_goal")),
        "duration_score": target_night.get("group_duration_score"),
        "solidity_score": target_night.get("group_solidity_score"),
        "regeneration_score": target_night.get("group_regeneration_score"),
        "sleep_stage_hr_stats": sleep_stage_hr_stats,
    }

    return {
        "raw_all": raw_data,
        "sleep_hr_samples": hr_dict,
        "summary": summary,
    }
