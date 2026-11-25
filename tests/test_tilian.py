"""题练离线单测:不联网、不花 token。"""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from tilian import agent, cli, mock, tools, web
from tilian.db import Database

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "topic-sample.json")


def load_sample() -> dict:
    with open(SAMPLE, encoding="utf-8") as f:
        return json.load(f)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "t.db"))
        s = load_sample()
        self.tid = self.db.add_topic(s["topic"], s["material"])
        self.qid = self.db.add_question(self.tid, "长护险的评估工具是____", "Barthel 指数", "原文:评估一般使用 Barthel 指数")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()


class TestJudge(unittest.TestCase):
    def test_exact_match(self):
        v = tools.judge("Barthel 指数", "Barthel 指数")
        self.assertTrue(v["correct"])

    def test_empty_answer(self):
        self.assertFalse(tools.judge("", "Barthel 指数")["correct"])

    def test_partial_keywords_still_wrong(self):
        v = tools.judge("保险", "服务给付、现金给付、混合给付")
        self.assertFalse(v["correct"])
        self.assertTrue(v["missing"])

    def test_coverage_above_threshold_passes(self):
        v = tools.judge("服务给付 现金给付", "服务给付、现金给付、混合给付")
        self.assertTrue(v["correct"])

    def test_normalize_strips_punct(self):
        self.assertEqual(tools.normalize("Barthel 指数。"), "barthel指数")


class TestSchedule(unittest.TestCase):
    def test_add_days_month_boundary(self):
        self.assertEqual(tools.add_days("2026-11-30", 1), "2026-12-01")
        self.assertEqual(tools.add_days("2026-02-28", 1), "2026-03-01")

    def test_next_review_correct_advances(self):
        r = tools.next_review("2026-11-25", True, 0)
        self.assertEqual(r["interval_days"], 1)
        self.assertEqual(r["stage"], 1)

    def test_next_review_wrong_resets(self):
        r = tools.next_review("2026-11-25", False, 3)
        self.assertEqual(r["stage"], 0)
        self.assertEqual(r["due_date"], "2026-11-26")


class TestDb(BaseCase):
    def test_question_has_review_row(self):
        self.assertIsNotNone(self.db.get_review(self.qid))

    def test_attempt_and_weak_points(self):
        self.db.add_attempt(self.qid, "乱答", False)
        self.db.add_attempt(self.qid, "乱答", False)
        ws = tools.weak_points(self.db.list_attempts(limit=50), self.db.list_questions())
        self.assertEqual(ws[0]["wrong"], 2)

    def test_due_list_and_set_review(self):
        self.db.set_review(self.qid, "2026-01-01", 1, 1, 3)
        due = self.db.due_questions("2026-11-25")
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["stage"], 1)

    def test_delete_question_cleans_children(self):
        self.db.add_attempt(self.qid, "x", False)
        self.assertTrue(self.db.delete_question(self.qid))
        self.assertIsNone(self.db.get_review(self.qid))


class TestOffline(BaseCase):
    def test_generate_blank_questions(self):
        r = mock.generate(self.db.get_topic(self.tid), 4)
        self.assertTrue(r["offline"])
        self.assertTrue(1 <= len(r["questions"]) <= 4)
        for q in r["questions"]:
            self.assertNotIn(q["answer"], q["stem"])

    def test_check_questions_drops_leaky(self):
        kept, dropped = agent.check_questions([
            {"stem": "答案是 Barthel 指数吗", "answer": "Barthel 指数"},
            {"stem": "筹资渠道包括____", "answer": "医保基金划转"},
        ])
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)

    def test_grade_returns_next(self):
        q = self.db.get_question(self.qid)
        r = agent.grade(q, "Barthel 指数", 0)
        self.assertTrue(r["correct"])
        self.assertEqual(r["next"]["stage"], 1)

    def test_explain_offline(self):
        q = self.db.get_question(self.qid)
        r = mock.explain(q, {"user_answer": "保险"})
        self.assertTrue(r["offline"])
        self.assertIn("Barthel", r["text"])


class TestCli(BaseCase):
    def _run(self, argv, db_path):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["--db", db_path] + argv)
        return buf.getvalue()

    def test_add_gen_answer(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = os.path.join(tmp.name, "c.db")
        s = load_sample()
        f = os.path.join(tmp.name, "m.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(s["material"])
        self.assertIn("知识点", self._run(["add", f, "--topic", "长期护理保险"], db_path))
        self.assertIn("出了", self._run(["--mock", "gen", "长期护理保险", "--n", "4"], db_path))
        out = self._run(["--mock", "answer", "1", "Barthel", "指数"], db_path)
        self.assertIn("判分依据", out)
        self.assertIn("下次复习", out)
        tmp.cleanup()


class TestWeb(BaseCase):
    def test_api_answer(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), web._make_handler(self.db, {"api_key": ""}, True))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        try:
            body = json.dumps({"qid": self.qid, "answer": "Barthel 指数"}).encode("utf-8")
            req = Request(f"http://127.0.0.1:{port}/api/answer", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=15) as resp:
                r = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(r["correct"])
            self.assertEqual(r["answer"], "Barthel 指数")
            with urlopen(f"http://127.0.0.1:{port}/api/topics", timeout=10) as resp:
                self.assertEqual(len(json.loads(resp.read().decode("utf-8"))), 1)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
