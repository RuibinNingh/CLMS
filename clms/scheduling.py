"""记忆算法与复习编排（对标 OMRS scheduling.py，按「一周两三次」的低频复习改造）。

与 OMRS 的相同点：时间衰减 time_decay、熟练度状态机、EF（易错因子）、SM-2 式间隔、
连续高分确认才算掌握（kill_streak）、已掌握题按衰减反解的分级周期复燃、Leech（顽固题）。

低频改造：
1. 到期日对齐到「复习日」（config.review_weekdays），不会出现周三到期、周五才复习却显示逾期两天
   的噪声；逾期天数也按对齐后的到期日算。
2. 评分用四档（不会 / 部分 / 基本 / 完整），比 0–10 主观分更适合语文主观题的「采分点」语感；
   默写只用 不会 / 有错字 / 全对 三档（对应 0 / 1 / 3）。
3. 按「时间预算」而不是题数排复习：阅读材料按篇只计一次阅读时间，同一篇里到期的小题尽量一起排。
4. 两种记忆类型（taxonomy.memory_kind）：记忆型（默写、实词虚词、文化常识）走上面的间隔重复；
   理解型（阅读主观题）做对一次就算掌握，衰减更慢，掌握后只隔很久抽查一次——重做同一道阅读题，
   测的多半是「记不记得答案」而不是阅读能力，反复排它价值很低。理解型的薄弱点落在「题型」上，
   排复习时优先补同题型的其它题（plan_session 的「薄弱题型」）。
"""

import datetime
import math

from .common import load_config, parse_date
from .taxonomy import GENRE_ORDER, MATERIAL_MINUTES, item_minutes

GRADES = {0: "不会", 1: "部分", 2: "基本", 3: "完整"}
DICTATION_GRADES = {0: "不会", 1: "有错字", 3: "全对"}
NEVER = "9999-12-31"             # 理解型掌握后且 skill_revive_days = 0：不再安排

DEFAULT_TUNING = {
    "decay_factor": 30.0, "decay_base": 5.0,
    "kill_streak": 2,            # 记忆型：连续几次「完整」才算掌握
    "ef_cold": 2, "ef_up": 0.15, "ef_down": 0.2,
    "first_interval": 2,         # 录入 / 答错后至少隔几天再复习
    "interval_1": 4, "interval_2": 9,
    "partial_factor": 0.7,       # 「基本」时间隔打折
    "leech_threshold": 3, "leech_bonus": 0.4,
    "new_bonus": 0.15,
    "new_age_days": 14.0, "new_age_weight": 0.25,   # 新题放得越久越靠前：满 new_age_days 天时再加 new_age_weight
    "overdue_divisor": 14.0, "overdue_weight": 0.3,
    "revive_threshold": 0.2, "revive_multiplier": 1.8,
    # 理解型（阅读主观题）
    "skill_kill_streak": 1,      # 一次「完整」即掌握
    "skill_basic_streak": 2,     # 连续两次「基本」及以上也算掌握
    "skill_partial_interval": 7, # 「基本」之后至少隔几天再看
    "skill_decay_factor": 90.0,  # 衰减更慢（记忆型是 decay_factor）
    "skill_revive_days": 120,    # 掌握后多久抽查一次；0 = 不再安排
    # 排复习
    "weak_qtype_threshold": 0.5, "weak_qtype_min": 2, "weak_qtype_bonus": 0.15,
    "recent_days": 2,            # 提前复习时跳过最近几天刚做过的题
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


def time_decay(mastery: float, days: int, t=DEFAULT_TUNING, factor=None) -> float:
    mastery = max(0.0, min(1.0, float(mastery or 0)))
    if mastery <= 0:
        return 0.0
    factor = t["decay_factor"] if factor is None else factor
    return mastery * math.exp(-max(0, days) / (mastery * factor + t["decay_base"]))


def revive_days(kills: int, t=DEFAULT_TUNING) -> int:
    base = (t["decay_factor"] + t["decay_base"]) * math.log(1.0 / max(0.01, min(0.95, t["revive_threshold"])))
    return max(7, int(round(base * (t["revive_multiplier"] ** max(0, kills - 1)))))


def skill_revive_days(kills: int, t=DEFAULT_TUNING):
    """理解型掌握后的抽查周期；skill_revive_days ≤ 0 时返回 None（不再安排）。"""
    base = float(t["skill_revive_days"])
    if base <= 0:
        return None
    return max(14, int(round(base * (t["revive_multiplier"] ** max(0, kills - 1)))))


def ef_to_difficulty(ef: float) -> float:
    ef = max(EF_MIN, min(EF_MAX, ef))
    return 1.0 + (EF_MAX - ef) / (EF_MAX - EF_MIN) * 9.0


def derive(created_at: str, events: list, weekdays, today: datetime.date, t=DEFAULT_TUNING, kind: str = "recall") -> dict:
    """按时间顺序重放一道小题的全部有效事件，得出当前记忆状态。

    events：[{kind: 'review'|'reencounter', grade, at}]，已作废的不传进来。
    「又录入一次」（reencounter，同一道题再次作为错题录入）按一次「不会」处理。
    kind：recall（记忆型，间隔重复）或 skill（理解型，做对一次即掌握、衰减慢、很久才抽查），见 taxonomy.memory_kind。
    """
    skill = kind == "skill"
    m, ef, reps, interval = 0.0, 2.5, 0, 0
    high_streak = basic_streak = wrong_streak = kills = reviews = 0
    created = parse_date(created_at) or today
    last = created
    due = align(last + datetime.timedelta(days=int(t["first_interval"])), weekdays)
    never = False
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
            basic_streak += 1
            wrong_streak = 0
            if skill:
                mastered = high_streak >= t["skill_kill_streak"]
            else:
                mastered = high_streak >= t["kill_streak"] and reps >= 1
            m = 1.0 if mastered else min(0.95, m + 0.35 * ef / 2.5)
        elif grade == 2:
            high_streak = wrong_streak = 0
            basic_streak += 1
            if skill and basic_streak >= t["skill_basic_streak"]:
                m = 1.0
            elif skill:                     # 理解型「基本」= 主要要点都有，至少算巩固中
                m = min(0.9, max(m + 0.2 * ef / 2.5, 0.6))
            else:
                m = min(0.9, m + 0.2 * ef / 2.5)
        else:
            high_streak = basic_streak = 0
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
                if skill:
                    interval = max(interval, int(t["skill_partial_interval"]))
        else:
            reps = 0
            interval = int(t["first_interval"]) + (1 if grade == 1 else 0)
        never = False
        if m >= 1.0:
            if not was_killed or grade == 3:
                kills += 1
            revive = skill_revive_days(kills, t) if skill else revive_days(kills, t)
            never = revive is None
            interval = revive or 0
        last = day
        due = align(day + datetime.timedelta(days=int(interval)), weekdays)

    days_since = max(0, (today - last).days)
    decayed = time_decay(m, days_since, t, t["skill_decay_factor"] if skill else None)
    leech = wrong_streak >= t["leech_threshold"] and m < 1.0
    overdue = 0 if never else max(0, (today - due).days)
    age = max(0, (today - created).days)
    priority = (1 - decayed) * (ef_to_difficulty(ef) / 10.0) + overdue / t["overdue_divisor"] * t["overdue_weight"]
    if leech:
        priority += t["leech_bonus"]
    if reviews == 0:
        priority += t["new_bonus"] + min(1.0, age / max(1.0, float(t["new_age_days"]))) * t["new_age_weight"]
    if m >= 1.0:
        status = "已掌握"
    elif reviews == 0:
        status = "新录入"
    elif m < 0.4:
        status = "待攻克"
    else:
        status = "巩固中"
    return {
        "kind": kind, "mastery": round(m, 3), "decayed": round(decayed, 3), "ef": round(ef, 2),
        "interval": int(interval), "due": NEVER if never else due.isoformat(), "last_review": last.isoformat(),
        "overdue_days": overdue, "reviews": reviews, "wrong_streak": wrong_streak,
        "high_streak": high_streak, "kills": kills, "leech": leech, "age_days": age,
        "last_grade": grades[-1] if grades else None,
        "priority": round(priority, 4), "status": status, "grades": grades[-8:],
    }


def grade_name(genre: str, value) -> str:
    return (DICTATION_GRADES if genre == "dictation" else GRADES).get(value, str(value))


def weak_qtypes(items: list, t=DEFAULT_TUNING) -> set:
    """理解型里整体掌握得差的题型：(genre, qtype)。只统计复习过的题，至少 weak_qtype_min 道才算数。"""
    agg = {}
    for it in items:
        sched = it["sched"]
        if it.get("suspended") or sched.get("kind") != "skill" or not sched["reviews"] or not it.get("qtype"):
            continue
        entry = agg.setdefault((it["genre"], it["qtype"]), [0, 0.0])
        entry[0] += 1
        entry[1] += sched["decayed"]
    return {key for key, (n, total) in agg.items()
            if n >= t["weak_qtype_min"] and total / n < t["weak_qtype_threshold"]}


def explain(item, horizon, today, weak=frozenset()) -> tuple:
    """推荐理由：(tag, 文字)。tag 给前端配色：leech / new / revive / overdue / due / weak / early。"""
    sched = item["sched"]
    due = parse_date(sched["due"])
    if sched["leech"]:
        return "leech", f"顽固 · 连错 {sched['wrong_streak']} 次"
    if sched["reviews"] == 0:
        age = sched.get("age_days", 0)
        return "new", f"新录入 · {age} 天未练" if age >= 3 else "新录入"
    if sched["status"] == "已掌握" and due and due <= horizon:
        return "revive", "掌握后抽查"
    last = sched.get("last_grade")
    tail = f" · 上次「{grade_name(item['genre'], last)}」" if last is not None and last < 3 else ""
    if due and due < today:
        return "overdue", f"逾期 {sched['overdue_days']} 天{tail}"
    if due and due <= horizon:
        return "due", "到期" + tail
    if (item["genre"], item.get("qtype")) in weak:
        return "weak", f"薄弱题型 · {item.get('qtype')}"
    return "early", "提前复习"


def plan_session(items: list, budget_minutes: float, today: datetime.date, horizon: datetime.date,
                 genres=None, fill: bool = True, qtypes=None, pinned=None, exclude=None, busy=None,
                 t=DEFAULT_TUNING) -> dict:
    """按时间预算挑题。items 为 projections 输出的全部小题（含 sched、genre、qtype、material_id）。

    pinned：用户自选、必须放进来的题（先占预算，理由「自选」）；exclude：用户从推荐里移掉的题；
    busy：已在未完成的复习里的题（不重复推荐）；qtypes：只从这些题型里推荐（不影响自选）。
    """
    budget = max(5.0, float(budget_minutes or 40))
    index = {it["id"]: it for it in items}
    exclude = set(exclude or ())
    busy = set(busy or ())
    pinned = [i for i in dict.fromkeys(pinned or ()) if i in index and i not in exclude]
    pinned_set = set(pinned)
    weak = weak_qtypes(items, t)
    pool = [it for it in items if not it.get("suspended") and (not genres or it["genre"] in genres)
            and (not qtypes or it.get("qtype") in qtypes) and it["id"] not in exclude and it["id"] not in pinned_set]
    skipped_busy = [it for it in pool if it["id"] in busy and it["sched"]["due"] <= horizon.isoformat()]
    pool = [it for it in pool if it["id"] not in busy]

    def rank(it):
        bonus = t["weak_qtype_bonus"] if (it["genre"], it.get("qtype")) in weak and it["sched"]["status"] != "已掌握" else 0
        return it["sched"]["priority"] + bonus

    horizon_s = horizon.isoformat()
    due = [it for it in pool if it["sched"]["due"] <= horizon_s and it["sched"]["status"] != "已掌握"]
    due.sort(key=lambda it: -rank(it))
    revive = [it for it in pool if it["sched"]["status"] == "已掌握" and it["sched"]["due"] <= horizon_s]
    revive.sort(key=lambda it: it["sched"]["due"])
    due += revive
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

    def take(it, tag, reason):
        nonlocal used
        used += cost(it)
        if it.get("material_id"):
            materials.add(it["material_id"])
        chosen.append({"id": it["id"], "tag": tag, "reason": reason,
                       "minutes": item_minutes(it["genre"], it.get("qtype", ""))})

    picked = set()
    for item_id in pinned:
        take(index[item_id], "manual", "自选")
        picked.add(item_id)
    for it in due:
        if it["id"] in picked:
            continue
        if chosen and used + cost(it) > budget:
            continue
        take(it, *explain(it, horizon, today, weak))
        picked.add(it["id"])
        for sib in by_material.get(it.get("material_id"), []):   # 同一篇里到期的一起做，只读一遍原文
            if sib["id"] not in picked and used + cost(sib) <= budget:
                take(sib, *explain(sib, horizon, today, weak))
                picked.add(sib["id"])
    if fill and used < budget * 0.8:
        recent = (today - datetime.timedelta(days=int(t["recent_days"]))).isoformat()
        extra = [it for it in pool if it["id"] not in due_ids and it["id"] not in picked
                 and it["sched"]["status"] != "已掌握"
                 and not (it["sched"]["reviews"] and it["sched"]["last_review"] >= recent)]
        extra.sort(key=lambda it: ((it["genre"], it.get("qtype")) not in weak, it["sched"]["decayed"], -rank(it)))
        for it in extra:
            if used + cost(it) <= budget:
                take(it, *explain(it, horizon, today, weak))
                picked.add(it["id"])

    order = {code: i for i, code in enumerate(GENRE_ORDER)}
    chosen.sort(key=lambda c: (order.get(index[c["id"]]["genre"], 9),
                               index[c["id"]].get("material_id") or "~",
                               index[c["id"]].get("order", 0), c["id"]))
    return {"items": chosen, "minutes": round(used, 1), "budget": budget,
            "due_total": len(due), "due_left": len([it for it in due if it["id"] not in picked]),
            "busy_skipped": len(skipped_busy), "pinned": len(pinned),
            "weak": [{"genre": g, "qtype": q} for g, q in sorted(weak)]}
