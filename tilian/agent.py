"""编排:出题(模型) + 判分(本地) + 讲解 + 排期(本地)。

分工是刻意写死的:题目让模型出,判分绝不给模型。
模型出的题还要过一道检查——题干不能把答案漏出来。
"""

from __future__ import annotations

from . import llm, mock, tools

MAX_STEPS = 12

GEN_SYSTEM = """你在根据一份知识点材料出练习题。只能依据材料,不许引入材料外的知识。

输出 JSON:
{"questions":[{"stem":"题干","answer":"参考答案(简短)","explain":"为什么是这个答案,引用材料原句"}]}

规则:
- 出 __N__ 道,覆盖材料里不同的要点,不要重复。
- 题干里不能出现答案本身,填空处用 ____ 代替。
- answer 控制在 12 个字以内,便于判分。
- explain 不超过 100 字,必须说出材料里的依据。
- 不要出选择题,只出填空或简答。"""

EXPLAIN_SYSTEM = """你在讲一道错题。学生答错了,你要指出错在哪,不要空泛鼓励。

输出 JSON:
{"text":"讲解正文,不超过 150 字"}

规则:
- 先给正确答案,再说依据(引用材料里的原句)。
- 指出学生答案缺了哪个关键点。
- 不要重复题干的废话,不要用「很棒」「加油」这类词。"""


def _use_model(config: dict | None, force_mock: bool) -> bool:
    if force_mock:
        return False
    return bool({**llm.default_config(), **(config or {})}.get("api_key"))


def _cfg(config: dict | None) -> dict:
    return {**llm.default_config(), **(config or {})}


def _chat(messages, config, max_tokens=1600) -> str:
    return llm.chat(messages, config=_cfg(config), temperature=0.3, max_tokens=max_tokens)


def check_questions(items: list[dict]) -> tuple[list[dict], list[str]]:
    """题干不能含答案、答案不能空、explain 不能过长。"""
    kept, dropped = [], []
    for q in items:
        stem = str(q.get("stem", "")).strip()
        answer = str(q.get("answer", "")).strip()
        explain = str(q.get("explain", "")).strip()
        if not stem or not answer:
            dropped.append("题干或答案为空")
            continue
        if tools.normalize(answer) in tools.normalize(stem):
            dropped.append(f"题干泄露答案:{stem[:20]}")
            continue
        if len(explain) > 140:
            explain = explain[:140]
        kept.append({"stem": stem, "answer": answer, "explain": explain})
    return kept, dropped


def generate(topic: dict, n: int = 5, config: dict | None = None, force_mock: bool = False) -> dict:
    material = topic.get("material", "")
    if len(material.strip()) < 60:
        raise llm.LLMError("材料太短(不足 60 字),先补知识点再出题")
    if not _use_model(config, force_mock):
        r = mock.generate(topic, n)
        r["dropped"] = []
        return r
    system = GEN_SYSTEM.replace("__N__", str(n))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"知识点:{topic['name']}\n材料:\n{material}"},
    ]
    raw = _chat(messages, config)
    data = llm.extract_json(raw)
    kept, dropped = check_questions(data.get("questions", [])[: n + 2])
    if not kept:
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "这些题不合规(题干泄露答案或为空)。请重出,题干用 ____ 代替答案。"},
        ]
        raw = _chat(messages, config)
        data = llm.extract_json(raw)
        kept, dropped2 = check_questions(data.get("questions", [])[:n])
        dropped += dropped2
    return {"topic": topic["name"], "questions": kept[:n], "dropped": dropped, "offline": False}


def explain(question: dict, attempt: dict, config: dict | None = None, force_mock: bool = False) -> dict:
    if not _use_model(config, force_mock):
        return mock.explain(question, attempt)
    verdict = tools.judge(attempt.get("user_answer", ""), question["answer"])
    raw = _chat([
        {"role": "system", "content": EXPLAIN_SYSTEM},
        {"role": "user", "content": (
            f"题目:{question['stem']}\n正确答案:{question['answer']}\n"
            f"参考答案说明:{question.get('explain', '')}\n"
            f"学生的答案:{attempt.get('user_answer', '')}\n"
            f"本地判分:{'对' if verdict['correct'] else '错'}({verdict['reason']}),"
            f"缺的关键词:{'、'.join(verdict['missing'][:4]) or '无'}"
        )},
    ], config, max_tokens=500)
    data = llm.extract_json(raw)
    text = str(data.get("text", "")).strip()
    return {"text": text or mock.explain(question, attempt)["text"], "offline": False,
            "checks": ["逐字核对:讲解里的答案与原题一致"] if question["answer"] in text else ["讲解里没复述答案,建议自行核对"]}


def grade(question: dict, user_answer: str, stage: int) -> dict:
    """判分与排期全在本地:模型不参与。"""
    verdict = tools.judge(user_answer, question["answer"])
    nxt = tools.next_review(tools.today(), verdict["correct"], stage)
    return {**verdict, "next": nxt, "offline": True}
