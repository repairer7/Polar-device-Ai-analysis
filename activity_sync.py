from loop_extras_sync import (
    BJT,
    format_duration_hm,
    parse_iso_dt,
    parse_iso_duration_seconds,
    safe_get_json,
)


def _extract_day_containers(raw):
    """兼容 list 或 dict 形式的活动样本响应，提取 activity-day-with-samples 列表。"""
    if isinstance(raw, list):
        containers = []
        for item in raw:
            if isinstance(item, dict):
                if "samples" in item and isinstance(item["samples"], dict):
                    containers.append(item["samples"])
                else:
                    containers.append(item)
        return containers
    if isinstance(raw, dict):
        return [raw]
    return []


def _summarize_active_windows(timed_steps, max_windows=6):
    """将步数 > 0 的采样聚合成活跃时段，便于 AI 了解主要活动时间分布。"""
    positive = [s for s in timed_steps if s["steps"] > 0]
    if not positive:
        return []

    windows = []
    cur_start = positive[0]["dt"]
    cur_end = positive[0]["dt"]
    cur_steps = positive[0]["steps"]

    for item in positive[1:]:
        gap_min = (item["dt"] - cur_end).total_seconds() / 60
        if gap_min <= 15:
            cur_end = item["dt"]
            cur_steps += item["steps"]
        else:
            windows.append((cur_start, cur_end, cur_steps))
            cur_start = item["dt"]
            cur_end = item["dt"]
            cur_steps = item["steps"]
    windows.append((cur_start, cur_end, cur_steps))

    # 过滤极小零散抖动，优先保留主要活跃时段
    significant = [w for w in windows if w[2] >= 50] or windows
    significant.sort(key=lambda w: w[2], reverse=True)
    top = sorted(significant[:max_windows], key=lambda w: w[0])

    result = []
    for s_dt, e_dt, steps in top:
        if s_dt == e_dt:
            label = s_dt.strftime("%H:%M")
        else:
            label = f"{s_dt.strftime('%H:%M')}-{e_dt.strftime('%H:%M')}"
        result.append({"time_range": label, "steps": steps})
    return result


def fetch_activity_data(base_url, headers, today_str, yesterday_str):
    """获取并处理跨天活动数据（步数时序、活动强度区间、久坐提醒及每日官方汇总）。"""
    raw_yesterday = safe_get_json(
        f"{base_url}/users/activities/samples",
        headers,
        params={"date": yesterday_str},
        label="activity-samples-yesterday",
    )
    raw_today = safe_get_json(
        f"{base_url}/users/activities/samples",
        headers,
        params={"date": today_str},
        label="activity-samples-today",
    )
    raw_activities = safe_get_json(
        f"{base_url}/users/activities",
        headers,
        params={
            "from": yesterday_str,
            "to": today_str,
            "steps": "true",
            "activity_zones": "true",
            "inactivity_stamps": "true",
        },
        label="activities-summary",
    )

    start_dt = parse_iso_dt(f"{yesterday_str}T21:00:00", target_tz=BJT)
    end_dt = parse_iso_dt(f"{today_str}T20:59:59", target_tz=BJT)

    combined_samples = []
    timed_step_samples = []
    seen_steps = set()

    zone_counts = {}
    seen_zones = set()

    inactivity_stamps = []
    seen_inactivity = set()

    def _collect_from_raw(raw, collect_steps=True):
        for entry in _extract_day_containers(raw):
            # 1. 步数样本
            if collect_steps:
                steps_block = entry.get("steps") or {}
                for s in steps_block.get("samples", []):
                    ts = s.get("timestamp")
                    ts_dt = parse_iso_dt(ts, naive_is_utc=False, target_tz=BJT)
                    if not ts_dt or not (start_dt <= ts_dt <= end_dt):
                        continue
                    key = ts_dt.isoformat()
                    if key in seen_steps:
                        continue
                    seen_steps.add(key)
                    step_val = s.get("steps") or 0
                    combined_samples.append(s)
                    timed_step_samples.append({
                        "dt": ts_dt,
                        "time": ts_dt.strftime("%H:%M"),
                        "steps": step_val,
                    })

            # 2. 活动强度区间样本
            zones_block = entry.get("activity_zones") or {}
            for z in zones_block.get("samples", []):
                ts = z.get("timestamp")
                ts_dt = parse_iso_dt(ts, naive_is_utc=False, target_tz=BJT)
                if not ts_dt or not (start_dt <= ts_dt <= end_dt):
                    continue
                zone_name = z.get("zone") or "UNKNOWN"
                z_key = (ts_dt.isoformat(), zone_name)
                if z_key in seen_zones:
                    continue
                seen_zones.add(z_key)
                zone_counts[zone_name] = zone_counts.get(zone_name, 0) + 1

            # 3. 久坐提醒时间戳
            raw_stamps = entry.get("inactivity_stamps") or []
            stamp_items = raw_stamps.get("samples", []) if isinstance(raw_stamps, dict) else raw_stamps
            for st in stamp_items:
                ts = (st.get("stamp") or st.get("timestamp") or st.get("time")) if isinstance(st, dict) else st
                ts_dt = parse_iso_dt(ts, naive_is_utc=False, target_tz=BJT)
                if not ts_dt or not (start_dt <= ts_dt <= end_dt):
                    continue
                s_key = ts_dt.isoformat()
                if s_key in seen_inactivity:
                    continue
                seen_inactivity.add(s_key)
                inactivity_stamps.append(ts_dt)

    _collect_from_raw(raw_yesterday)
    _collect_from_raw(raw_today)
    if raw_activities:
        _collect_from_raw(raw_activities, collect_steps=not bool(timed_step_samples))

    timed_step_samples.sort(key=lambda x: x["dt"])
    inactivity_stamps.sort()

    # 解析官方每日活动汇总 (/users/activities)
    daily_summary = {"has_data": False}
    if isinstance(raw_activities, list) and raw_activities:
        def _summary_local_date(item):
            # start_time / end_time 文档说明为 UTC
            dt = parse_iso_dt(item.get("end_time") or item.get("start_time"), naive_is_utc=True, target_tz=BJT)
            return dt.strftime("%Y-%m-%d") if dt else ""

        target_act = next((a for a in raw_activities if _summary_local_date(a) == today_str), None)
        if target_act is None:
            target_act = sorted(
                raw_activities,
                key=lambda x: x.get("end_time") or x.get("start_time") or "",
            )[-1]

        active_sec = parse_iso_duration_seconds(target_act.get("active_duration"))
        inactive_sec = parse_iso_duration_seconds(target_act.get("inactive_duration"))
        dist_m = target_act.get("distance_from_steps")
        daily_score = target_act.get("daily_activity")
        daily_summary = {
            "has_data": True,
            "active_duration_min": round(active_sec / 60, 1) if active_sec is not None else None,
            "active_duration_str": format_duration_hm(active_sec),
            "inactive_duration_min": round(inactive_sec / 60, 1) if inactive_sec is not None else None,
            "inactive_duration_str": format_duration_hm(inactive_sec),
            "daily_activity_goal_pct": f"{round(daily_score, 1)}%" if daily_score is not None else None,
            "daily_activity_goal_completion_pct": round(daily_score, 1) if daily_score is not None else None,
            "calories": target_act.get("calories"),
            "active_calories": target_act.get("active_calories"),
            "steps_official_day": target_act.get("steps"),
            "distance_m": round(dist_m, 1) if dist_m is not None else None,
            "inactivity_alert_count": target_act.get("inactivity_alert_count"),
        }

    step_values = [s["steps"] for s in timed_step_samples]
    total_zones = sum(zone_counts.values())
    zone_pcts = (
        {k: round(v / total_zones * 100, 1) for k, v in zone_counts.items()}
        if total_zones > 0
        else {}
    )

    stats = {
        "total_steps": sum(step_values),
        "max_step_intensity": max(step_values) if step_values else 0,
        "count": len(timed_step_samples),
        "active_windows": _summarize_active_windows(timed_step_samples),
        "zone_counts": zone_counts,
        "zone_pcts": zone_pcts,
        "daily_summary": daily_summary,
    }
    if inactivity_stamps:
        stats["inactivity_stamps"] = [dt.strftime("%H:%M") for dt in inactivity_stamps]

    return {
        "raw_yesterday": raw_yesterday,
        "raw_today": raw_today,
        "raw_activities": raw_activities,
        "filtered_samples": combined_samples,
        "timed_step_samples": timed_step_samples,
        "stats": stats,
    }
