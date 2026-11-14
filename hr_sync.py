import math
from datetime import timedelta
from loop_extras_sync import BJT, parse_iso_dt, safe_get_json


def _calc_basic_stats(values):
    if not values:
        return {"avg": None, "min": None, "max": None, "std": None, "count": 0}
    n = len(values)
    mean_v = sum(values) / n
    var_v = sum((v - mean_v) ** 2 for v in values) / n
    return {
        "avg": round(mean_v, 1),
        "min": min(values),
        "max": max(values),
        "std": round(math.sqrt(var_v), 1),
        "count": n,
    }


def _percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return round(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f), 1)


def _merge_sample_stages(items, max_gap_min=10):
    """将间隔不超过 max_gap_min 分钟的同类异常采样点合并为连续阶段。"""
    if not items:
        return []
    groups = [[items[0]]]
    for item in items[1:]:
        gap_min = (item["dt"] - groups[-1][-1]["dt"]).total_seconds() / 60.0
        if gap_min <= max_gap_min:
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _format_stage_list(groups, extra_builder=None):
    results = []
    for grp in groups:
        s_dt = grp[0]["dt"]
        e_dt = grp[-1]["dt"]
        hrs = [x["hr"] for x in grp]
        # 单点按默认 5 分钟采样窗口估算，多点按首尾间隔 + 5 分钟估算
        dur_min = max(5, int(round((e_dt - s_dt).total_seconds() / 60.0)) + 5)
        time_range = (
            s_dt.strftime("%H:%M")
            if s_dt == e_dt
            else f"{s_dt.strftime('%H:%M')}-{e_dt.strftime('%H:%M')}"
        )
        entry = {
            "time_range": time_range,
            "duration_min": dur_min,
            "sample_count": len(grp),
            "avg_hr": round(sum(hrs) / len(hrs), 1),
            "max_hr": max(hrs),
            "min_hr": min(hrs),
        }
        if extra_builder:
            entry.update(extra_builder(grp))
        results.append(entry)
    return results


def _parse_sleep_bound(val):
    if not val or not isinstance(val, str):
        return None
    return parse_iso_dt(val.replace(" ", "T"), target_tz=BJT)


def fetch_hr_data(
    base_url,
    headers,
    today_str,
    yesterday_str,
    sleep_summary=None,
    activity_results=None,
    exercises_results=None,
    physical_info=None,
):
    """获取跨天连续心率并进行多维分段、恢复动力学与异常阶段深度检测。"""
    raw_yesterday = safe_get_json(
        f"{base_url}/users/continuous-heart-rate/{yesterday_str}",
        headers,
        label="hr-yesterday",
    )
    raw_today = safe_get_json(
        f"{base_url}/users/continuous-heart-rate/{today_str}",
        headers,
        label="hr-today",
    )

    combined_samples = []
    timeline = []
    seen_dts = set()

    def _collect(raw, date_str, is_yesterday):
        if not isinstance(raw, dict):
            return
        for s in raw.get("heart_rate_samples", []):
            st = s.get("sample_time")
            hr = s.get("heart_rate", 0)
            if not st or not isinstance(hr, (int, float)) or hr <= 0:
                continue
            if is_yesterday and st < "21:00:00":
                continue
            if not is_yesterday and st >= "21:00:00":
                continue
            dt = parse_iso_dt(f"{date_str}T{st}", target_tz=BJT)
            if not dt or dt in seen_dts:
                continue
            seen_dts.add(dt)
            combined_samples.append(s)
            timeline.append({
                "dt": dt,
                "date": date_str,
                "time": st,
                "hr": int(round(hr)),
            })

    _collect(raw_yesterday, yesterday_str, True)
    _collect(raw_today, today_str, False)
    timeline.sort(key=lambda x: x["dt"])

    if not timeline:
        return {
            "raw_yesterday": raw_yesterday,
            "raw_today": raw_today,
            "filtered_samples": [],
            "stats": {
                "has_data": False,
                "avg": 0,
                "max": 0,
                "min": 0,
                "count": 0,
            },
        }

    # --- 1. 跨模态上下文准备 ---
    sleep_summary = sleep_summary or {}
    sleep_start_dt = _parse_sleep_bound(sleep_summary.get("start_time"))
    sleep_end_dt = _parse_sleep_bound(sleep_summary.get("end_time"))
    if sleep_start_dt and sleep_end_dt and sleep_start_dt < sleep_end_dt:
        sleep_window_source = "sleep_record"
    else:
        sleep_start_dt = parse_iso_dt(f"{today_str}T00:00:00", target_tz=BJT)
        sleep_end_dt = parse_iso_dt(f"{today_str}T07:30:00", target_tz=BJT)
        sleep_window_source = "estimated_default"

    exercise_windows = (exercises_results or {}).get("exercise_windows") or []
    timed_steps = (activity_results or {}).get("timed_step_samples") or []
    step_data_available = bool(timed_steps)

    def _get_exercise_sport(dt):
        for w in exercise_windows:
            if w["start_dt"] <= dt <= w["end_dt"]:
                return w.get("sport") or "EXERCISE"
        return None

    def _sum_steps_in_range(start_dt, end_dt):
        if not timed_steps:
            return 0
        return sum(s["steps"] for s in timed_steps if start_dt <= s["dt"] <= end_dt)

    def _get_window_steps(dt):
        return _sum_steps_in_range(dt - timedelta(minutes=10), dt + timedelta(minutes=5))

    for item in timeline:
        dt = item["dt"]
        in_sleep = sleep_start_dt <= dt <= sleep_end_dt
        ex_sport = _get_exercise_sport(dt)
        c_steps = _get_window_steps(dt)
        item["in_sleep"] = in_sleep
        item["exercise_sport"] = ex_sport
        item["concurrent_steps"] = c_steps
        item["is_resting"] = (ex_sport is None) and (c_steps <= 15)

    # --- 2. 全天基础统计与动态个人阈值 ---
    hr_values = [x["hr"] for x in timeline]
    sorted_hrs = sorted(hr_values)
    overall = _calc_basic_stats(hr_values)
    max_item = max(timeline, key=lambda x: x["hr"])
    min_item = min(timeline, key=lambda x: x["hr"])

    sleep_items = [x for x in timeline if x["in_sleep"]]
    awake_items = [x for x in timeline if not x["in_sleep"]]
    sleep_hrs = [x["hr"] for x in sleep_items]
    awake_hrs = [x["hr"] for x in awake_items]
    sleep_hr_avg = round(sum(sleep_hrs) / len(sleep_hrs), 1) if sleep_hrs else None

    phys = physical_info or {}
    phys_rhr = phys.get("resting_heart_rate")
    p10 = _percentile(sorted_hrs, 10)
    if isinstance(phys_rhr, (int, float)) and phys_rhr > 0:
        baseline_rhr = phys_rhr
        baseline_source = "physical_info"
    elif sleep_hr_avg is not None:
        baseline_rhr = sleep_hr_avg
        baseline_source = "sleep_hr_avg"
    else:
        baseline_rhr = p10
        baseline_source = "p10_percentile"

    awake_resting_high_threshold = max(95, round(baseline_rhr + 28))
    sleep_high_threshold = (
        max(78, round(sleep_hr_avg + 15))
        if sleep_hr_avg is not None
        else max(78, round(baseline_rhr + 18))
    )
    sleep_low_threshold = 40
    awake_low_threshold = 48
    jump_threshold = 22

    # --- 3. 五大生理阶段对比 ---
    noon_dt = parse_iso_dt(f"{today_str}T12:00:00", target_tz=BJT)
    evening_dt = parse_iso_dt(f"{today_str}T18:00:00", target_tz=BJT)

    stage_buckets = {
        "pre_sleep": [x["hr"] for x in timeline if x["dt"] < sleep_start_dt],
        "sleep": sleep_hrs,
        "morning": [x["hr"] for x in timeline if (not x["in_sleep"]) and sleep_end_dt < x["dt"] <= noon_dt],
        "afternoon": [x["hr"] for x in timeline if (not x["in_sleep"]) and max(sleep_end_dt, noon_dt) < x["dt"] <= evening_dt],
        "evening": [x["hr"] for x in timeline if (not x["in_sleep"]) and x["dt"] > max(sleep_end_dt, evening_dt)],
    }
    stage_stats = {k: _calc_basic_stats(v) for k, v in stage_buckets.items()}
    daytime_awake_avg = round(sum(awake_hrs) / len(awake_hrs), 1) if awake_hrs else None

    # --- 4. 夜间心率恢复动力学 ---
    sleep_hr_dynamics = {"has_data": bool(sleep_items), "sleep_window_source": sleep_window_source}
    if sleep_items:
        nadir_item = min(sleep_items, key=lambda x: x["hr"])
        sleep_span_sec = max(1.0, (sleep_end_dt - sleep_start_dt).total_seconds())
        nadir_pos_pct = round(
            min(100.0, max(0.0, (nadir_item["dt"] - sleep_start_dt).total_seconds() / sleep_span_sec * 100)),
            1,
        )
        mid_idx = max(1, len(sleep_items) // 2)
        first_half = [x["hr"] for x in sleep_items[:mid_idx]]
        second_half = [x["hr"] for x in sleep_items[mid_idx:]] or first_half

        if nadir_pos_pct < 50:
            recovery_eval = "夜间最低心率出现在前半夜，副交感神经恢复迅速"
        elif nadir_pos_pct <= 70:
            recovery_eval = "夜间最低心率出现在中段，夜间恢复节奏正常"
        else:
            recovery_eval = "夜间最低心率延迟至后半夜/临醒前，提示睡前饮食、压力或交感兴奋影响恢复"

        sleep_hr_dynamics.update({
            "sleep_avg": sleep_hr_avg,
            "sleep_min": nadir_item["hr"],
            "nadir_time": nadir_item["dt"].strftime("%H:%M"),
            "nadir_position_pct": nadir_pos_pct,
            "first_half_avg": round(sum(first_half) / len(first_half), 1),
            "second_half_avg": round(sum(second_half) / len(second_half), 1),
            "recovery_evaluation": recovery_eval,
        })

    # --- 5. 24小时逐时心率紧凑趋势 ---
    hourly_buckets = {}
    for x in timeline:
        h_key = x["dt"].strftime("%Y-%m-%d %H")
        hourly_buckets.setdefault(h_key, []).append(x["hr"])
    hourly_curve = []
    for h_key in sorted(hourly_buckets.keys()):
        vals = hourly_buckets[h_key]
        hh = h_key.split(" ")[1]
        hourly_curve.append(f"{hh}h:{round(sum(vals) / len(vals))}({min(vals)}-{max(vals)})")

    # --- 6. 异常与高波动阶段检测 ---
    resting_elevated_pts = [
        x for x in timeline
        if (not x["in_sleep"]) and x["is_resting"] and x["hr"] >= awake_resting_high_threshold
    ]
    sleep_elevated_pts = [
        x for x in timeline
        if x["in_sleep"] and x["hr"] >= sleep_high_threshold
    ]
    activity_elevated_pts = [
        x for x in timeline
        if (not x["in_sleep"]) and (not x["is_resting"]) and x["hr"] >= awake_resting_high_threshold
    ]
    low_hr_pts = [
        x for x in timeline
        if (x["in_sleep"] and x["hr"] < sleep_low_threshold)
        or ((not x["in_sleep"]) and x["is_resting"] and x["hr"] < awake_low_threshold)
    ]

    resting_elevated_stages = _format_stage_list(
        _merge_sample_stages(resting_elevated_pts),
        extra_builder=lambda grp: {
            "steps": _sum_steps_in_range(grp[0]["dt"] - timedelta(minutes=10), grp[-1]["dt"] + timedelta(minutes=5)),
            "note": (
                "静息状态心率达心动过速警戒线(>=100bpm)"
                if max(x["hr"] for x in grp) >= 100
                else (
                    "非活动静息期心率异常偏高"
                    if step_data_available
                    else "清醒期心率偏高（无同期步数样本校验）"
                )
            ),
        },
    )

    sleep_elevated_stages = _format_stage_list(
        _merge_sample_stages(sleep_elevated_pts),
        extra_builder=lambda grp: {
            "note": "睡眠期间心率异常偏高（超出夜间阈值）",
        },
    )

    activity_elevated_stages = _format_stage_list(
        _merge_sample_stages(activity_elevated_pts),
        extra_builder=lambda grp: {
            "steps": _sum_steps_in_range(grp[0]["dt"] - timedelta(minutes=10), grp[-1]["dt"] + timedelta(minutes=5)),
            "sports": sorted({x["exercise_sport"] for x in grp if x["exercise_sport"]}),
            "note": "正常活动或运动引起的心率升高",
        },
    )

    low_hr_stages = _format_stage_list(
        _merge_sample_stages(low_hr_pts),
        extra_builder=lambda grp: {
            "period": "睡眠期" if any(x["in_sleep"] for x in grp) else "清醒静息期",
            "note": "心率偏低/心动过缓时段",
        },
    )

    sudden_fluctuations = []
    for prev_item, curr_item in zip(timeline, timeline[1:]):
        gap_min = (curr_item["dt"] - prev_item["dt"]).total_seconds() / 60.0
        if gap_min > 10:
            continue
        if prev_item["exercise_sport"] or curr_item["exercise_sport"]:
            continue
        if not (prev_item["is_resting"] and curr_item["is_resting"]):
            continue
        delta = curr_item["hr"] - prev_item["hr"]
        if abs(delta) >= jump_threshold:
            sudden_fluctuations.append({
                "time_range": f"{prev_item['dt'].strftime('%H:%M')}->{curr_item['dt'].strftime('%H:%M')}",
                "from_hr": prev_item["hr"],
                "to_hr": curr_item["hr"],
                "delta": f"{delta:+d}",
                "steps": curr_item["concurrent_steps"],
                "period": "睡眠期" if (prev_item["in_sleep"] or curr_item["in_sleep"]) else "清醒静息期",
            })

    stats = {
        "has_data": True,
        "avg": overall["avg"],
        "max": max_item["hr"],
        "max_time": max_item["dt"].strftime("%H:%M"),
        "min": min_item["hr"],
        "min_time": min_item["dt"].strftime("%H:%M"),
        "std": overall["std"],
        "p10": p10,
        "p50": _percentile(sorted_hrs, 50),
        "p90": _percentile(sorted_hrs, 90),
        "count": overall["count"],
        "daytime_awake_avg": daytime_awake_avg,
        "baseline_rhr": baseline_rhr,
        "baseline_source": baseline_source,
        "step_context_available": step_data_available,
        "thresholds_used": {
            "awake_resting_high_bpm": awake_resting_high_threshold,
            "sleep_high_bpm": sleep_high_threshold,
            "sleep_low_bpm": sleep_low_threshold,
            "awake_low_bpm": awake_low_threshold,
            "sudden_jump_bpm": jump_threshold,
        },
        "stage_stats": stage_stats,
        "sleep_hr_dynamics": sleep_hr_dynamics,
        "hourly_curve": hourly_curve,
        "anomalies": {
            "resting_elevated_stages": resting_elevated_stages,
            "sleep_elevated_stages": sleep_elevated_stages,
            "activity_elevated_stages": activity_elevated_stages,
            "sudden_fluctuations": sudden_fluctuations,
            "low_hr_stages": low_hr_stages,
        },
    }

    return {
        "raw_yesterday": raw_yesterday,
        "raw_today": raw_today,
        "filtered_samples": combined_samples,
        "stats": stats,
    }
