"""记忆算法与复习编排（对标 OMRS scheduling.py，按「一周两三次」的低频复习改造）。

与 OMRS 的相同点：时间衰减 time_decay、熟练度状态机、EF（易错因子）、SM-2 式间隔、
连续高分确认才算掌握（kill_streak）、已掌握题按衰减反解的分级周期复燃、Leech（顽固题）。

低频改造：
1. 到期日对齐到「复习日」（config.review_weekdays），不会出现周三到期、周五才复习却显示逾期两天
   的噪声；逾期天数也按对齐后的到期日算。
2. 评分用四档（不会 / 部分 / 基本 / 完整），比 0–10 主观分更适合语文主观题的「采分点」语感；
   默写只用 不会 / 有错字 / 全对 三档（对应 0 / 1 / 3）。
3. 按「时间预算」而不是题数排复习：阅读材料按篇只计一次阅读时间，同一篇里到期的小题尽量一起排。
"""

import datetime
import math

from .common import load_config, parse_date
from .taxonomy import GENRE_ORDER, MATERIAL_MINUTES, item_minutes

GRADES = {0: "不会", 1: "部分", 2: "基本", 3: "完整"}
DICTATION_GRADES = {0: "不会", 1: "有错字", 3: "全对"}

DEFAULT_TUNING = {
    "decay_factor": 30.0, "decay_base": 5.0,
    "kill_streak": 2,            # 连续几次「完整」才算掌握
    "ef_cold": 2, "ef_up": 0.15, "ef_down": 0.2,
    "first_interval": 2,         # 录入 / 答错后至少隔几天再复习
    "interval_1": 4, "interval_2": 9,
    "partial_factor": 0.7,       # 「基本」时间隔打折
    "leech_threshold": 3, "leech_bonus": 0.4,
    "new_bonus": 0.15,
    "overdue_divisor": 14.0, "overdue_weight": 0.3,
    "revive_threshold": 0.2, "revive_multiplier": 1.8,
}
EF_MIN, EF_MAX = 1.3, 3.0


def load_tuning(vault: str) -> dict:
    merged = dict(DEFAULT_TUNING)
    user = load_config(vault).get("tuning")
    if isinstance(user, dict):
        for key, value in user.items():
            if key in merged and isinstance(value, (int, float)):
                merged[key] = value
    return merged


def review_weekdays(vault: str) -> list:
    raw = load_config(vault).get("review_weekdays")
    days = sorted({int(d) for d in raw if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6}) if isinstance(raw, list) else []
    return days


def align(date: datetime.date, weekdays) -> datetime.date:
    if not weekdays:
        return date
    for offset in range(7):
        cand = date + datetime.timedelta(days=offset)
        if cand.weekday() in weekdays:
            return cand
    return date


def next_review_day(today: datetime.date, weekdays) -> datetime.date:
    return align(today, weekdays)


def time_decay(mastery: float, days: int, t=DEFAULT_TUNING) -> float:
    mastery = max(0.0, min(1.0, float(mastery or 0)))
    if mastery <= 0:
        return 0.0
    return mastery * math.exp(-max(0, days) / (mastery * t["decay_factor"] + t["decay_base"]))


def revive_days(kills: int, t=DEFAULT_TUNING) -> int:
    base = (t["decay_factor"] + t["decay_base"]) * math.log(1.0 / max(0.01, min(0.95, t["revive_threshold"])))
    return max(7, int(round(base * (t["revive_multiplier"] ** max(0, kills - 1)))))


def ef_to_difficulty(ef: float) -> float:
    ef = max(EF_MIN, min(EF_MAX, ef))
    return 1.0 + (EF_MAX - ef) / (EF_MAX - EF_MIN) * 9.0


def derive(created_at: str, events: list, weekdays, today: datetime.date, t=DEFAULT_TUNING) -> dict:
    """按时间顺序重放一道小题的全部有效事件，得出当前记忆状态。

    events：[{kind: 'review'|'reencounter', grade, at}]，已作废的不传进来。
    「又录入一次」（reencounter，同一道题再次作为错题录入）按一次「不会」处理。
    """
    m, ef, reps, interval = 0.0, 2.5, 0, 0
    high_streak = wrong_streak = kills = reviews = 0
    last = parse_date(created_at) or today
    due = align(last + datetime.timedelta(days=int(t["first_interval"])), weekdays)
    grades = []
    for ev in sorted(events, key=lambda e: e.get("at") or ""):
        day = parse_date(ev.get("at")) or last
        grade = 0 if ev.get("kind") == "reencounter" else max(0, min(3, int(ev.get("grade", 0))))
        if ev.get("kind") == "review":
            reviews += 1
            grades.append(grade)
        was_killed = m >= 1.0
        if grade == 3:
            high_streak += 1
            wrong_streak = 0
            m = 1.0 if (high_streak >= t["kill_streak"] and reps >= 1) else min(0.95, m + 0.35 * ef / 2.5)
        elif grade == 2:
            high_streak = wrong_streak = 0
            m = min(0.9, m + 0.2 * ef / 2.5)
        else:
            high_streak = 0
            wrong_streak += 1
            m = m * (0.6 if grade == 1 else 0.3)
        if reps >= t["ef_cold"]:
            if grade == 3:
                ef = min(EF_MAX, ef + t["ef_up"])
            elif grade <= 1:
                ef = max(EF_MIN, ef - t["ef_down"])
        if grade >= 2:
            reps += 1
            interval = t["interval_1"] if reps == 1 else t["interval_2"] if reps == 2 else round(interval * ef)
            if grade == 2:
                interval = max(2, round(interval * t["partial_factor"]))
        else:
            reps = 0
            interval = int(t["first_interval"]) + (1 if grade == 1 else 0)
        if m >= 1.0:
            if not was_killed or grade == 3:
                kills += 1
            interval = revive_days(kills, t)
        last = day
        due = align(day + datetime.timedelta(days=int(interval)), weekdays)

    days_since = max(0, (today - last).days)
    decayed = time_decay(m, days_since, t)
    leech = wrong_streak >= t["leech_threshold"] and m < 1.0
    overdue = max(0, (today - due).days)
    priority = (1 - decayed) * (ef_to_difficulty(ef) / 10.0) + overdue / t["overdue_divisor"] * t["overdue_weight"]
    if leech:
        priority += t["leech_bonus"]
    if reviews == 0:
        priority += t["new_bonus"]
    if m >= 1.0:
        status = "已掌握"
    elif reviews == 0:
        status = "新录入"
    elif m < 0.4:
        status = "待攻克"
    else:
        status = "巩固中"
    return {
        "mastery": round(m, 3), "decayed": round(decayed, 3), "ef": round(ef, 2),
        "interval": int(interval), "due": due.isoformat(), "last_review": last.isoformat(),
        "overdue_days": overdue, "reviews": reviews, "wrong_streak": wrong_streak,
        "high_streak": high_streak, "kills": kills, "leech": leech,
        "priority": round(priority, 4), "status": status, "grades": grades[-8:],
    }


def _reason(item, horizon, today) -> str:
    sched = item["sched"]
    due = parse_date(sched["due"])
    if sched["leech"]:
        return "顽固"
    if sched["reviews"] == 0:
        return "新录入"
    if due and due < today:
        return f"逾期 {sched['overdue_days']} 天"
    if due and due <= horizon:
        return "到期"
    return "提前复习"


def plan_session(items: list, budget_minutes: float, today: datetime.date, horizon: datetime.date,
                 genres=None, fill: bool = True) -> dict:
    """按时间预算挑题。items 为 projections 输出的小题（含 sched、genre、qtype、material_id）。"""
    budget = max(5.0, float(budget_minutes or 40))
    pool = [it for it in items if not it.get("suspended") and (not genres or it["genre"] in genres)]
    due = [it for it in pool if it["sched"]["due"] <= horizon.isoformat() and it["sched"]["status"] != "已掌握"]
    due += [it for it in pool if it["sched"]["status"] == "已掌握" and it["sched"]["due"] <= horizon.isoformat()]
    due.sort(key=lambda it: -it["sched"]["priority"])
    due_ids = {it["id"] for it in due}
    by_material = {}
    for it in due:
        if it.get("material_id"):
            by_material.setdefault(it["material_id"], []).append(it)

    chosen, used, materials = [], 0.0, set()

    def cost(it):
        c = item_minutes(it["genre"], it.get("qtype", ""))
        if it.get("material_id") and it["material_id"] not in materials:
            c += MATERIAL_MINUTES.get(it["genre"], 0.0)
        return c

    def take(it, reason):
        nonlocal used
        used += cost(it)
        if it.get("material_id"):
            materials.add(it["material_id"])
        chosen.append({"id": it["id"], "reason": reason, "minutes": item_minutes(it["genre"], it.get("qtype", ""))})

    picked = set()
    for it in due:
        if it["id"] in picked:
            continue
        if chosen and used + cost(it) > budget:
            continue
        take(it, _reason(it, horizon, today))
        picked.add(it["id"])
        for sib in by_material.get(it.get("material_id"), []):   # 同一篇里到期的一起做，只读一遍原文
            if sib["id"] not in picked and used + cost(sib) <= budget:
                take(sib, _reason(sib, horizon, today))
                picked.add(sib["id"])
    if fill and used < budget * 0.8:
        extra = [it for it in pool if it["id"] not in due_ids and it["sched"]["status"] != "已掌握"]
        extra.sort(key=lambda it: (it["sched"]["decayed"], -it["sched"]["priority"]))
        for it in extra:
            if used + cost(it) <= budget:
                take(it, "提前复习")
                picked.add(it["id"])

    index = {it["id"]: it for it in pool}
    order = {code: i for i, code in enumerate(GENRE_ORDER)}
    chosen.sort(key=lambda c: (order.get(index[c["id"]]["genre"], 9),
                               index[c["id"]].get("material_id") or "~",
                               index[c["id"]].get("order", 0), c["id"]))
    return {"items": chosen, "minutes": round(used, 1), "budget": budget,
            "due_total": len(due), "due_left": len([it for it in due if it["id"] not in picked])}
