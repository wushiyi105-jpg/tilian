"""纯函数层:判分、关键词覆盖、艾宾浩斯排期、错题统计。

判分必须本地做:让模型给自己判分等于让学生自己打卷。
排期更不能含糊,日期错一天,整个复习计划就散了。
"""

from __future__ import annotations

import calendar
import re
from datetime import date

# 艾宾浩斯:答对后往后推的间隔(天)。答错回到第 0 档。
INTERVALS = (1, 2, 4, 7, 15, 30)

_STOP = ("的", "了", "是", "在", "和", "与", "及", "或", "也", "就", "都", "而", "其", "为", "不")


def normalize(text: str) -> str:
    t = re.sub(r"[\s\u3000，。、；：！？,.;:!?\"“”‘’（）()【】\[\]—…·]", "", text or "")
    return t.lower()


def split_sentences(text: str) -> list[str]:
    out, buf = [], ""
    for ch in text or "":
        buf += ch
        if ch in "。！？；!?;\n":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def keywords(text: str, limit: int = 6) -> list[str]:
    """抽实词作为判分依据:2~4 字片段里挑出现频次高、长度长的。"""
    clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", " ", text or "")
    grams: dict[str, int] = {}
    for seg in clean.split():
        for n in (4, 3, 2):
            for i in range(len(seg) - n + 1):
                g = seg[i : i + n]
                if g in _STOP or g.isdigit():
                    continue
                grams[g] = grams.get(g, 0) + 1
    ordered = sorted(grams.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    picked: list[str] = []
    for g, _c in ordered:
        if any(g in p or p in g for p in picked):
            continue
        picked.append(g)
        if len(picked) >= limit:
            break
    return picked


def judge(user_answer: str, answer: str) -> dict:
    """判分三档:与参考答案一致 / 关键词覆盖够 / 不对。

    覆盖阈值取答案关键词的 60%,至少 1 个 —— 答对一半不算对。
    """
    u = normalize(user_answer)
    a = normalize(answer)
    if not u:
        return {"correct": False, "coverage": 0.0, "missing": keywords(answer), "reason": "没有作答"}
    if u == a:
        return {"correct": True, "coverage": 1.0, "missing": [], "reason": "与参考答案一致"}
    kws = keywords(answer)
    if not kws:
        ok = u in a or a in u
        return {"correct": ok, "coverage": 0.0, "missing": [], "reason": "答案太短,按包含关系判"}
    hit = [k for k in kws if k in u]
    coverage = round(len(hit) / len(kws), 2)
    missing = [k for k in kws if k not in u]
    need = max(1, int(round(len(kws) * 0.6)))
    correct = len(hit) >= need
    reason = "关键词覆盖达标" if correct else f"只覆盖 {len(hit)}/{len(kws)} 个关键词"
    return {"correct": correct, "coverage": coverage, "missing": missing, "reason": reason}


def add_days(day: str, n: int) -> str:
    """日期加天数。月份长度一律走 calendar.monthrange,绝不写死 31 天。"""
    d = date.fromisoformat(day)
    y, m, dd = d.year, d.month, d.day + n
    while True:
        last = calendar.monthrange(y, m)[1]
        if dd <= last:
            break
        dd -= last
        m += 1
        if m > 12:
            m = 1
            y += 1
    return date(y, m, dd).isoformat()


def next_review(today: str, correct: bool, stage: int) -> dict:
    """答对进一档,答错退回第 0 档、明天再来。"""
    stage = max(0, min(len(INTERVALS) - 1, stage))
    if correct:
        interval = INTERVALS[stage]
        next_stage = min(len(INTERVALS) - 1, stage + 1)
    else:
        interval = 1
        next_stage = 0
    return {"due_date": add_days(today, interval), "interval_days": interval, "stage": next_stage}


def today() -> str:
    return date.today().isoformat()


def weak_points(attempts: list[dict], questions: list[dict]) -> list[dict]:
    """错得最多的题:按题目统计错误次数。"""
    by_q: dict[int, int] = {}
    for a in attempts:
        if not a["correct"]:
            by_q[a["question_id"]] = by_q.get(a["question_id"], 0) + 1
    qmap = {q["id"]: q for q in questions}
    out = []
    for qid, n in sorted(by_q.items(), key=lambda kv: -kv[1]):
        q = qmap.get(qid)
        if q:
            out.append({"question_id": qid, "stem": q["stem"], "wrong": n})
    return out


TOOLS = [
    {"name": "get_material", "desc": "取回该知识点的原文材料。", "args": {}},
    {"name": "existing_questions", "desc": "已出过的题干,避免重复出题。", "args": {}},
]


def tool_list_text() -> str:
    return "\n".join(f"- {t['name']}({', '.join(t['args']) or '无'}):{t['desc']}" for t in TOOLS)


def execute(name: str, args: dict, topic: dict, questions: list[dict]) -> dict:
    if name == "get_material":
        return {"topic": topic["name"], "material": topic.get("material", "")}
    if name == "existing_questions":
        return {"stems": [q["stem"] for q in questions]}
    return {"error": f"未知工具: {name}"}


def dump(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
