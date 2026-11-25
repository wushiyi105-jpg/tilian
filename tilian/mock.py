"""离线模式:从知识点材料里挖空出题 + 本地判分 + 错因归类。

规则引擎不会凭空编题——它只会把材料里的关键词挖掉,做成填空题。
好处是每道题的答案都能在材料里找到原文,不存在的知识点不会被伪造出来。
"""

from __future__ import annotations

from . import tools

TARGET = 5


def generate(topic: dict, limit: int = TARGET) -> dict:
    material = topic.get("material", "")
    sents = [s for s in tools.split_sentences(material) if 12 <= len(s) <= 90]
    items, used = [], set()
    for s in sents:
        kws = [k for k in tools.keywords(s, 4) if s.count(k) == 1 and len(k) >= 3]
        if not kws:
            continue
        kw = kws[0]
        if kw in used:
            continue
        used.add(kw)
        stem = s.replace(kw, "____", 1)
        items.append({"stem": f"填空:{stem}", "answer": kw, "explain": f"原句:{s}"})
        if len(items) >= limit:
            break
    return {
        "topic": topic["name"],
        "questions": items,
        "offline": True,
        "checks": [f"离线模式:从材料中挖空生成 {len(items)} 道填空题,未编题"],
    }


def explain(question: dict, attempt: dict) -> dict:
    verdict = tools.judge(attempt.get("user_answer", ""), question["answer"])
    reason = "概念记错" if verdict["coverage"] == 0 else "要点漏了"
    lines = [f"正确答案:{question['answer']}"]
    if question.get("explain"):
        lines.append(question["explain"])
    lines.append(f"你的答案:{attempt.get('user_answer', '')}")
    lines.append(f"错因初判:{reason}({verdict['reason']})")
    if verdict["missing"]:
        lines.append("没答到的关键词:" + "、".join(verdict["missing"][:4]))
    return {"offline": True, "text": "\n".join(lines)}


def schedule_text(next_r: dict) -> str:
    return (
        f"下次复习:{next_r['due_date']}(间隔 {next_r['interval_days']} 天,"
        f"进入第 {next_r['stage']} 档)"
    )
