"""命令行入口:python -m tilian <命令> [选项]。"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, agent, llm, mock, tools
from . import db as dbmod
from .llm import LLMError

MOCK_BANNER = (
    "⚠️  当前为离线模式(未配置 LLM_API_KEY),题目由材料挖空生成,讲解走规则。\n"
    "   在 .env 填入 LLM_API_KEY 后,出题与错因讲解交给大模型(判分始终在本地)。\n"
)

_OPEN: list = []


def _db(args) -> dbmod.Database:
    db = dbmod.Database(getattr(args, "db", None))
    _OPEN.append(db)
    return db


def _close_all() -> None:
    for d in _OPEN:
        d.close()
    _OPEN.clear()


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def cmd_add(args):
    db = _db(args)
    material = _read_input(args.file)
    if len(material.strip()) < 60:
        print("❌ 材料太短(不足 60 字),出不了题", file=sys.stderr)
        sys.exit(1)
    tid = db.add_topic(args.topic, material)
    print(f"✅ 知识点 [{tid}] {args.topic}  {len(material)} 字")


def cmd_topics(args):
    db = _db(args)
    ts = db.list_topics()
    if args.json:
        print(json.dumps(ts, ensure_ascii=False, indent=2))
        return
    if not ts:
        print("(空)用 tilian add 导入知识点材料")
        return
    for t in ts:
        print(f"[{t['id']}] {t['name']}  {t['chars']} 字  {t['questions']} 题")


def cmd_gen(args):
    db = _db(args)
    topic = db.get_topic(args.topic)
    if not topic:
        print(f"❌ 找不到知识点:{args.topic}", file=sys.stderr)
        sys.exit(1)
    r = agent.generate(topic, args.n, config=llm.config_from_args(args), force_mock=args.mock)
    ids = []
    for q in r["questions"]:
        ids.append(db.add_question(topic["id"], q["stem"], q["answer"], q.get("explain", "")))
    if args.json:
        print(json.dumps({**r, "ids": ids}, ensure_ascii=False, indent=2))
        return
    print(f"📝 {r['topic']} 出了 {len(ids)} 道题" + ("  ·  离线模式" if r.get("offline") else ""))
    for qid, q in zip(ids, r["questions"]):
        print(f"\n[{qid}] {q['stem']}")
    if r.get("dropped"):
        print("\n! 丢弃 " + str(len(r["dropped"])) + " 道不合规的题:" + ";".join(r["dropped"][:3]))


def cmd_list(args):
    db = _db(args)
    qs = db.list_questions(db.get_topic(args.topic)["id"] if args.topic and db.get_topic(args.topic) else None)
    if args.json:
        print(json.dumps(qs, ensure_ascii=False, indent=2))
        return
    if not qs:
        print("(还没有题)")
        return
    for q in qs:
        print(f"[{q['id']}] {q['stem']}")


def cmd_show(args):
    db = _db(args)
    q = db.get_question(args.qid)
    if not q:
        print(f"❌ 没有这道题:{args.qid}", file=sys.stderr)
        sys.exit(1)
    r = db.get_review(q["id"])
    print(f"[{q['id']}] {q['topic']}\n{q['stem']}\n")
    print(f"答案:{q['answer']}")
    if q["explain"]:
        print(q["explain"])
    if r:
        print(f"\n下次复习:{r['due_date']}(第 {r['stage']} 档,间隔 {r['interval_days']} 天)")


def cmd_answer(args):
    db = _db(args)
    q = db.get_question(args.qid)
    if not q:
        print(f"❌ 没有这道题:{args.qid}", file=sys.stderr)
        sys.exit(1)
    ua = " ".join(args.answer) if isinstance(args.answer, list) else args.answer
    stage = (db.get_review(q["id"]) or {}).get("stage", 0)
    r = agent.grade(q, ua, stage)
    aid = db.add_attempt(q["id"], ua, r["correct"])
    db.set_review(q["id"], r["next"]["due_date"], r["next"]["interval_days"], r["next"]["stage"], 3)
    mark = "✅ 对" if r["correct"] else "❌ 错"
    print(f"{mark}  [{q['id']}] {q['stem']}")
    print(f"参考答案:{q['answer']}")
    print(f"判分依据:{r['reason']}(覆盖 {r['coverage']})")
    if r["missing"]:
        print("没答到:" + "、".join(r["missing"][:4]))
    print(mock.schedule_text(r["next"]))
    print(f"（记录 #{aid},可 tilian explain {q['id']} 看讲解）")


def cmd_explain(args):
    db = _db(args)
    q = db.get_question(args.qid)
    if not q:
        print(f"❌ 没有这道题:{args.qid}", file=sys.stderr)
        sys.exit(1)
    attempts = db.list_attempts(q["id"], 1)
    if not attempts:
        print("❌ 这道题还没有作答记录", file=sys.stderr)
        sys.exit(1)
    r = agent.explain(q, attempts[0], config=llm.config_from_args(args), force_mock=args.mock)
    print(("🧭 错因讲解" + ("  ·  离线模式" if r.get("offline") else "")) + "\n")
    print(r["text"])
    for c in r.get("checks", []):
        print(f"  · {c}")


def cmd_due(args):
    db = _db(args)
    qs = db.due_questions(tools.today() if not args.date else args.date)
    if args.json:
        print(json.dumps(qs, ensure_ascii=False, indent=2))
        return
    if not qs:
        print("今天没有到期该复习的题。")
        return
    print(f"📅 今天该复习 {len(qs)} 道:")
    for q in qs:
        print(f"[{q['id']}] {q['topic']}  {q['stem']}")


def cmd_wrong(args):
    db = _db(args)
    ws = tools.weak_points(db.list_attempts(limit=200), db.list_questions())
    if not ws:
        print("还没有错题。")
        return
    print("🔁 错题排行:")
    for w in ws[:10]:
        print(f"[{w['question_id']}] 错 {w['wrong']} 次  {w['stem']}")


def cmd_rm(args):
    db = _db(args)
    print("🗑  已删除" if db.delete_question(args.qid) else "❌ 没有这道题")


def cmd_stats(args):
    print(json.dumps(_db(args).stats(), ensure_ascii=False))


def cmd_web(args):
    from . import web

    web.serve(host=args.host, port=args.port, db_path=args.db, force_mock=args.mock)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tilian", description="题练 · 刷题备考:出题、判分、讲解、艾宾浩斯复习。")
    p.add_argument("--version", action="version", version=f"tilian {__version__}")
    p.add_argument("--mock", action="store_true", help="强制离线模式")
    p.add_argument("--json", action="store_true")
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.add_argument("--api-key")
    p.add_argument("--db")

    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="导入知识点材料")
    a.add_argument("file")
    a.add_argument("--topic", required=True)
    a.set_defaults(func=cmd_add)

    tp = sub.add_parser("topics", help="知识点列表")
    tp.set_defaults(func=cmd_topics)

    g = sub.add_parser("gen", help="出题")
    g.add_argument("topic")
    g.add_argument("--n", type=int, default=5)
    g.set_defaults(func=cmd_gen)

    ls = sub.add_parser("list", help="题目列表")
    ls.add_argument("--topic")
    ls.set_defaults(func=cmd_list)

    sh = sub.add_parser("show", help="看一道题")
    sh.add_argument("qid", type=int)
    sh.set_defaults(func=cmd_show)

    an = sub.add_parser("answer", help="作答并判分")
    an.add_argument("qid", type=int)
    an.add_argument("answer", nargs="+")
    an.set_defaults(func=cmd_answer)

    ex = sub.add_parser("explain", help="错因讲解")
    ex.add_argument("qid", type=int)
    ex.set_defaults(func=cmd_explain)

    du = sub.add_parser("due", help="今天该复习的题")
    du.add_argument("--date")
    du.set_defaults(func=cmd_due)

    wr = sub.add_parser("wrong", help="错题排行")
    wr.set_defaults(func=cmd_wrong)

    rm = sub.add_parser("rm", help="删一道题")
    rm.add_argument("qid", type=int)
    rm.set_defaults(func=cmd_rm)

    st = sub.add_parser("stats", help="统计")
    st.set_defaults(func=cmd_stats)

    wb = sub.add_parser("web", help="启动 Web 界面")
    wb.add_argument("--host", default="127.0.0.1")
    wb.add_argument("--port", type=int, default=8000)
    wb.set_defaults(func=cmd_web)
    return p


GLOBAL_FLAGS = ("--mock", "--json")
GLOBAL_OPTS = ("--model", "--base-url", "--api-key", "--db")


def hoist_globals(argv: list[str]) -> list[str]:
    g, rest = [], []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in GLOBAL_FLAGS:
            g.append(a)
            i += 1
        elif a in GLOBAL_OPTS:
            g += [a, argv[i + 1]] if i + 1 < len(argv) else [a]
            i += 2
        elif any(a.startswith(o + "=") for o in GLOBAL_OPTS):
            g.append(a)
            i += 1
        else:
            rest.append(a)
            i += 1
    return g + rest


def main(argv=None):
    args = build_parser().parse_args(hoist_globals(list(sys.argv[1:] if argv is None else argv)))
    if not args.mock and args.command in ("gen", "explain"):
        if not llm.config_from_args(args).get("api_key"):
            print(MOCK_BANNER, file=sys.stderr)
    try:
        args.func(args)
    except LLMError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    finally:
        _close_all()


if __name__ == "__main__":
    main()
