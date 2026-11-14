import re
import requests
from datetime import datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8))

_ISO_FRAC_RE = re.compile(r"\.(\d+)")
_ISO_NO_SEC_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})([+-]\d{2}:?\d{2}|Z)?$")
_ISO_DUR_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

CARDIO_LOAD_STATUS_MAP = {
    "LOAD_STATUS_NOT_AVAILABLE": "暂无负荷评估",
    "DETRAINING": "训练减量/负荷下降",
    "MAINTAINING": "负荷维持",
    "PRODUCTIVE": "高效负荷",
    "OVERREACHING": "负荷过高/过度疲劳风险",
    "RECOVERY_AFTER_OVERREACHING": "高负荷后恢复期",
    "PRODUCTIVE_DROPPED_FROM_OVERREACHING": "从过度恢复至高效负荷",
    "PRODUCTIVE_ALMOST_OVERREACHING": "高效但接近负荷上限",
    "UNRECOGNIZED": "未识别",
}

ALERTNESS_CLASS_MAP = {
    "GRADE_CLASSIFICATION_WEAK": "较弱",
    "GRADE_CLASSIFICATION_FAIR": "一般",
    "GRADE_CLASSIFICATION_STRONG": "良好",
    "GRADE_CLASSIFICATION_EXCELLENT": "极佳",
}

SLEEP_INERTIA_MAP = {
    "SLEEP_INERTIA_NO_INERTIA": "无明显起床困倦",
    "SLEEP_INERTIA_MILD": "轻度起床困倦",
    "SLEEP_INERTIA_MODERATE": "中度起床困倦",
    "SLEEP_INERTIA_HEAVY": "重度起床困倦",
}

CIRCADIAN_QUALITY_MAP = {
    "CIRCADIAN_BEDTIME_QUALITY_WEAK": "节律较弱",
    "CIRCADIAN_BEDTIME_QUALITY_COMPROMISED": "节律受损/不规律",
    "CIRCADIAN_BEDTIME_QUALITY_CLEARLY_RECOGNIZABLE": "节律清晰稳定",
}


def parse_iso_dt(ts_str, naive_is_utc=False, target_tz=BJT, naive_tz=None):
    """兼容 Python 3.10 的 ISO-8601 时间解析，统一输出带 target_tz 时区的 datetime。"""
    if not ts_str or not isinstance(ts_str, str):
        return None
    s = ts_str.strip()
    if not s:
        return None

    m_no_sec = _ISO_NO_SEC_RE.match(s)
    if m_no_sec:
        tz_part = m_no_sec.group(2) or ""
        s = f"{m_no_sec.group(1)}:00{tz_part}"

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # Python 3.10 fromisoformat 仅支持 0/3/6 位小数秒，这里统一规整为 6 位
    s = _ISO_FRAC_RE.sub(lambda m: "." + (m.group(1) + "000000")[:6], s)

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None

    if dt.tzinfo is None:
        if naive_tz is not None:
            dt = dt.replace(tzinfo=naive_tz)
        elif naive_is_utc:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.replace(tzinfo=target_tz)

    return dt.astimezone(target_tz)


def parse_iso_duration_seconds(dur_str):
    """解析 ISO-8601 时长（如 PT3H11M、PT18H23M30S）为秒数。"""
    if not dur_str or not isinstance(dur_str, str):
        return None
    m = _ISO_DUR_RE.match(dur_str.strip())
    if not m:
        return None
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = float(m.group("seconds") or 0.0)
    return round(days * 86400 + hours * 3600 + minutes * 60 + seconds, 1)


def format_duration_hm(seconds):
    """将秒数格式化为 X小时Y分钟。"""
    if seconds is None or seconds < 0:
        return None
    total_min = int(round(seconds / 60))
    h, m = divmod(total_min, 60)
    if h > 0:
        return f"{h}小时{m}分"
    return f"{m}分钟"


def safe_get_json(url, headers, params=None, label="", timeout=15):
    """通用 Polar GET 请求封装，非 200 状态安全降级。"""
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code not in (204, 404):
            print(f"[{label or url}] 接口返回状态码 {resp.status_code}")
        return None
    except Exception as e:
        print(f"[{label or url}] 请求失败: {e}")
        return None


def _group_hour_ranges(slots):
    """将连续的 [(start_dt, end_dt)] 小时段合并为紧凑字符串列表，如 ['09:00-12:00']。"""
    if not slots:
        return []
    slots_sorted = sorted(slots, key=lambda x: x[0])
    merged = [list(slots_sorted[0])]
    for start_dt, end_dt in slots_sorted[1:]:
        if abs((start_dt - merged[-1][1]).total_seconds()) <= 60:
            merged[-1][1] = end_dt
        else:
            merged.append([start_dt, end_dt])
    return [f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s, e in merged]


def fetch_physical_info(base_url, headers):
    """获取用户基础生理基准（静息心率、最大心率、VO2max、睡眠目标等）。"""
    raw = safe_get_json(f"{base_url}/users/physical-info", headers, label="physical-info")
    if not isinstance(raw, dict):
        return {"raw_all": None, "summary": {"has_data": False}}

    sleep_goal_sec = parse_iso_duration_seconds(raw.get("sleep_goal"))
    summary = {
        "has_data": True,
        "resting_heart_rate": raw.get("resting_heart_rate"),
        "maximum_heart_rate": raw.get("maximum_heart_rate"),
        "vo2_max": raw.get("vo2_max"),
        "aerobic_threshold": raw.get("aerobic_threshold"),
        "anaerobic_threshold": raw.get("anaerobic_threshold"),
        "sleep_goal_min": round(sleep_goal_sec / 60, 1) if sleep_goal_sec else None,
        "typical_day": raw.get("typical_day"),
        "training_background": raw.get("training_background"),
    }
    return {"raw_all": raw, "summary": summary}


def fetch_biosensing_data(base_url, headers, today_str, yesterday_str):
    """获取 Polar Loop Elixir 生物传感数据（夜间皮肤温度、体温、皮肤佩戴接触检测）。"""
    window_start = parse_iso_dt(f"{yesterday_str}T21:00:00", target_tz=BJT)
    window_end = parse_iso_dt(f"{today_str}T20:59:59", target_tz=BJT)
    date_params = {"from": yesterday_str, "to": today_str}

    # 1. 夜间睡眠皮肤温度及 28 天基线偏离
    skin_raw = safe_get_json(
        f"{base_url}/users/biosensing/skintemperature",
        headers,
        params=date_params,
        label="skin-temperature",
    )
    skin_temp_summary = {"has_data": False}
    if isinstance(skin_raw, list) and skin_raw:
        target = next((item for item in skin_raw if item.get("sleep_date") == today_str), None)
        if target is None:
            target = sorted(skin_raw, key=lambda x: x.get("sleep_date") or "")[-1]
        skin_temp_summary = {
            "has_data": True,
            "sleep_date": target.get("sleep_date"),
            "skin_temp_c": target.get("sleep_time_skin_temperature_celsius"),
            "deviation_from_baseline_c": target.get("deviation_from_baseline_celsius"),
        }

    # 2. 体温采样周期汇总
    body_raw = safe_get_json(
        f"{base_url}/users/biosensing/bodytemperature",
        headers,
        params=date_params,
        label="body-temperature",
    )
    body_temps = []
    measurement_types = set()
    if isinstance(body_raw, list):
        for period in body_raw:
            p_start = parse_iso_dt(period.get("start_time"), naive_is_utc=True, target_tz=BJT)
            p_end = parse_iso_dt(period.get("end_time"), naive_is_utc=True, target_tz=BJT)
            if p_start and p_end and (p_end < window_start or p_start > window_end):
                continue
            m_type = period.get("measurement_type")
            if m_type:
                measurement_types.add(m_type)
            for s in period.get("samples", []):
                val = s.get("temperature_celsius")
                if val is not None:
                    body_temps.append(val)

    body_temp_summary = {"has_data": bool(body_temps)}
    if body_temps:
        body_temp_summary.update({
            "avg_c": round(sum(body_temps) / len(body_temps), 2),
            "min_c": round(min(body_temps), 2),
            "max_c": round(max(body_temps), 2),
            "sample_count": len(body_temps),
            "measurement_types": sorted(measurement_types),
        })

    # 3. 皮肤接触 / 未佩戴检测
    contact_raw = safe_get_json(
        f"{base_url}/users/biosensing/skincontacts",
        headers,
        params=date_params,
        label="skin-contacts",
    )
    off_wrist_events = []
    non_contact_windows = []
    if isinstance(contact_raw, list):
        for period in contact_raw:
            p_start = parse_iso_dt(period.get("start_time"), naive_is_utc=True, target_tz=BJT)
            p_end = parse_iso_dt(period.get("end_time"), naive_is_utc=True, target_tz=BJT)
            if not p_start or (p_end and p_end < window_start) or p_start > window_end:
                continue
            off_start = None
            for ch in sorted(
                period.get("skin_contact_changes", []),
                key=lambda x: x.get("recording_time_delta_milliseconds", 0),
            ):
                delta_ms = ch.get("recording_time_delta_milliseconds", 0)
                ev_dt = p_start + timedelta(milliseconds=delta_ms)
                if ch.get("skin_contact") is False:
                    if window_start <= ev_dt <= window_end:
                        off_wrist_events.append(ev_dt.strftime("%H:%M"))
                    if off_start is None:
                        off_start = ev_dt
                elif ch.get("skin_contact") is True and off_start is not None:
                    non_contact_windows.append((off_start, ev_dt))
                    off_start = None
            if off_start is not None and p_end is not None:
                non_contact_windows.append((off_start, p_end))

    skin_contact_summary = {
        "has_data": isinstance(contact_raw, list) and len(contact_raw) > 0,
        "off_wrist_count": len(off_wrist_events),
        "off_wrist_times": off_wrist_events[:8],
    }

    has_any = (
        skin_temp_summary.get("has_data")
        or body_temp_summary.get("has_data")
        or skin_contact_summary.get("has_data")
    )
    return {
        "raw_all": {
            "skin_temperature": skin_raw,
            "body_temperature": body_raw,
            "skin_contacts": contact_raw,
        },
        "non_contact_windows": non_contact_windows,
        "summary": {
            "has_data": bool(has_any),
            "skin_temperature": skin_temp_summary,
            "body_temperature": body_temp_summary,
            "skin_contacts": skin_contact_summary,
        },
    }


def fetch_sleepwise_data(base_url, headers, today_str, yesterday_str, sleep_summary=None):
    """获取 SleepWise 日间清醒度预测与生物钟最佳入睡时间窗。"""
    alert_raw = safe_get_json(f"{base_url}/users/sleepwise/alertness", headers, label="sleepwise-alertness")
    bedtime_raw = safe_get_json(f"{base_url}/users/sleepwise/circadian-bedtime", headers, label="sleepwise-circadian")

    alertness_summary = {"has_data": False}
    if isinstance(alert_raw, list) and alert_raw:
        def _item_end_date(item):
            offset = item.get("sleep_timezone_offset_minutes")
            tz = timezone(timedelta(minutes=offset)) if offset is not None else BJT
            dt = parse_iso_dt(item.get("period_end_time"), naive_is_utc=True, target_tz=tz)
            return dt.strftime("%Y-%m-%d") if dt else ""

        target = next((x for x in alert_raw if _item_end_date(x) == today_str), None)
        if target is None:
            target = sorted(alert_raw, key=lambda x: x.get("period_end_time") or "")[-1]

        offset = target.get("sleep_timezone_offset_minutes")
        local_tz = timezone(timedelta(minutes=offset)) if offset is not None else BJT

        awake_start_dt = parse_iso_dt(f"{today_str}T07:00:00", target_tz=local_tz)
        if isinstance(sleep_summary, dict):
            wake_str = sleep_summary.get("end_time") or sleep_summary.get("sleep_end_time")
            wake_dt = parse_iso_dt(wake_str, target_tz=local_tz)
            if wake_dt and awake_start_dt:
                awake_start_dt = awake_start_dt.replace(
                    hour=wake_dt.hour,
                    minute=wake_dt.minute,
                    second=0,
                    microsecond=0,
                )

        peak_slots = []
        low_slots = []
        daytime_slot_count = 0
        for h in target.get("hourly_data", []):
            s_dt = parse_iso_dt(h.get("start_time"), naive_is_utc=True, target_tz=local_tz)
            e_dt = parse_iso_dt(h.get("end_time"), naive_is_utc=True, target_tz=local_tz)
            if not s_dt or not e_dt:
                continue
            if s_dt.strftime("%Y-%m-%d") != today_str:
                continue
            if (awake_start_dt and s_dt < awake_start_dt) or s_dt.hour >= 21:
                continue

            daytime_slot_count += 1
            lvl = h.get("alertness_level", "")
            if lvl in ("ALERTNESS_LEVEL_HIGH", "ALERTNESS_LEVEL_VERY_HIGH"):
                peak_slots.append((s_dt, e_dt))
            elif lvl in ("ALERTNESS_LEVEL_LOW", "ALERTNESS_LEVEL_VERY_LOW", "ALERTNESS_LEVEL_MINIMAL"):
                low_slots.append((s_dt, e_dt))

        low_hours = _group_hour_ranges(low_slots)
        if daytime_slot_count > 0 and not low_hours:
            low_hours = ["日间精力平稳，无明显犯困低谷"]

        cls_key = target.get("grade_classification")
        inertia_key = target.get("sleep_inertia")
        alertness_summary = {
            "has_data": True,
            "grade": target.get("grade"),
            "grade_classification": ALERTNESS_CLASS_MAP.get(cls_key, cls_key),
            "sleep_inertia": SLEEP_INERTIA_MAP.get(inertia_key, inertia_key),
            "peak_alertness_hours": _group_hour_ranges(peak_slots),
            "low_alertness_hours": low_hours,
        }

    circadian_summary = {"has_data": False}
    if isinstance(bedtime_raw, list) and bedtime_raw:
        def _bed_date(item):
            offset = item.get("sleep_timezone_offset_minutes")
            tz = timezone(timedelta(minutes=offset)) if offset is not None else BJT
            dt = parse_iso_dt(item.get("period_end_time"), naive_is_utc=True, target_tz=tz)
            return dt.strftime("%Y-%m-%d") if dt else ""

        target_bed = next((x for x in bedtime_raw if _bed_date(x) == today_str), None)
        if target_bed is None:
            target_bed = sorted(bedtime_raw, key=lambda x: x.get("period_end_time") or "")[-1]

        offset = target_bed.get("sleep_timezone_offset_minutes")
        local_tz = timezone(timedelta(minutes=offset)) if offset is not None else BJT

        pref_s = parse_iso_dt(target_bed.get("preferred_sleep_period_start_time"), naive_is_utc=True, target_tz=local_tz)
        pref_e = parse_iso_dt(target_bed.get("preferred_sleep_period_end_time"), naive_is_utc=True, target_tz=local_tz)
        gate_s = parse_iso_dt(target_bed.get("sleep_gate_start_time"), naive_is_utc=True, target_tz=local_tz)
        gate_e = parse_iso_dt(target_bed.get("sleep_gate_end_time"), naive_is_utc=True, target_tz=local_tz)
        q_key = target_bed.get("quality")

        circadian_summary = {
            "has_data": True,
            "quality": CIRCADIAN_QUALITY_MAP.get(q_key, q_key),
            "preferred_sleep_window": f"{pref_s.strftime('%H:%M')}-{pref_e.strftime('%H:%M')}" if pref_s and pref_e else None,
            "sleep_gate_window": f"{gate_s.strftime('%H:%M')}-{gate_e.strftime('%H:%M')}" if gate_s and gate_e else None,
        }

    return {
        "raw_all": {"alertness": alert_raw, "circadian_bedtime": bedtime_raw},
        "summary": {
            "has_data": bool(alertness_summary.get("has_data") or circadian_summary.get("has_data")),
            "alertness": alertness_summary,
            "circadian_bedtime": circadian_summary,
        },
    }


def fetch_cardio_load_data(base_url, headers, today_str, yesterday_str):
    """获取心肺负荷（Cardio Load、近期疲劳 Strain、长期耐受 Tolerance）。"""
    raw = safe_get_json(f"{base_url}/users/cardio-load", headers, label="cardio-load")
    if not isinstance(raw, list) or not raw:
        return {"raw_all": None, "summary": {"has_data": False}}

    by_date = {item.get("date"): item for item in raw if item.get("date")}
    target = by_date.get(today_str)
    if not target or target.get("cardio_load_status") == "LOAD_STATUS_NOT_AVAILABLE":
        valid_items = [
            item for item in sorted(raw, key=lambda x: x.get("date") or "")
            if item.get("cardio_load_status") not in (None, "LOAD_STATUS_NOT_AVAILABLE")
        ]
        if valid_items:
            target = valid_items[-1]
        elif target is None:
            target = by_date.get(yesterday_str) or sorted(raw, key=lambda x: x.get("date") or "")[-1]

    status_key = target.get("cardio_load_status")
    return {
        "raw_all": raw,
        "summary": {
            "has_data": True,
            "date": target.get("date"),
            "cardio_load_status": status_key,
            "cardio_load_status_cn": CARDIO_LOAD_STATUS_MAP.get(status_key, status_key),
            "cardio_load": target.get("cardio_load"),
            "strain": target.get("strain"),
            "tolerance": target.get("tolerance"),
            "cardio_load_ratio": target.get("cardio_load_ratio"),
        },
    }


def fetch_exercises_data(base_url, headers, today_str, yesterday_str):
    """获取统计区间内的运动/自动识别训练记录，用于运动负荷分析及心率异常排除。"""
    raw = safe_get_json(
        f"{base_url}/exercises",
        headers,
        params={"samples": "false", "zones": "true"},
        label="exercises",
    )
    if not isinstance(raw, list):
        return {"raw_all": None, "exercise_windows": [], "summary": {"has_data": False, "count": 0, "sessions": []}}

    window_start = parse_iso_dt(f"{yesterday_str}T21:00:00", target_tz=BJT)
    window_end = parse_iso_dt(f"{today_str}T20:59:59", target_tz=BJT)

    sessions = []
    exercise_windows = []

    for ex in raw:
        start_raw = ex.get("start_time") or ex.get("start-time")
        offset_min = ex.get("start_time_utc_offset")
        if offset_min is None:
            offset_min = ex.get("start-time-utc-offset")
        naive_tz = timezone(timedelta(minutes=offset_min)) if offset_min is not None else BJT

        start_dt = parse_iso_dt(start_raw, naive_is_utc=False, target_tz=BJT, naive_tz=naive_tz)
        if not start_dt:
            continue

        dur_sec = parse_iso_duration_seconds(ex.get("duration")) or 0
        end_dt = start_dt + timedelta(seconds=dur_sec)

        if end_dt < window_start or start_dt > window_end:
            continue

        hr_obj = ex.get("heart_rate") or ex.get("heart-rate") or {}
        tlp = ex.get("training_load_pro") or ex.get("training-load-pro") or {}
        sport = ex.get("detailed_sport_info") or ex.get("detailed-sport-info") or ex.get("sport") or "OTHER"

        exercise_windows.append({
            "start_dt": start_dt,
            "end_dt": end_dt,
            "sport": sport,
        })
        sessions.append({
            "sport": sport,
            "start_time": start_dt.strftime("%m-%d %H:%M"),
            "end_time": end_dt.strftime("%H:%M"),
            "duration_min": round(dur_sec / 60, 1),
            "calories": ex.get("calories"),
            "distance_m": round(ex.get("distance"), 1) if ex.get("distance") is not None else None,
            "hr_avg": hr_obj.get("average"),
            "hr_max": hr_obj.get("maximum"),
            "training_load": ex.get("training_load") if ex.get("training_load") is not None else ex.get("training-load"),
            "cardio_load": tlp.get("cardio_load") if "cardio_load" in tlp else tlp.get("cardio-load"),
        })

    return {
        "raw_all": raw,
        "exercise_windows": exercise_windows,
        "summary": {
            "has_data": bool(sessions),
            "count": len(sessions),
            "sessions": sessions,
        },
    }
