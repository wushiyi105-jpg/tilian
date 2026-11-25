"""题练的持久层:知识点、题目、作答记录、复习计划。

复习计划单独一张表,以 question_id 为主键 —— 一道题只有一条当前进度,
历史作答留在 attempts 里,两个用途分开放。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tilian.db")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("TILIAN_DB") or DEFAULT_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    material TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER NOT NULL,
                    stem TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    explain TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL,
                    user_answer TEXT NOT NULL,
                    correct INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    question_id INTEGER PRIMARY KEY,
                    due_date TEXT NOT NULL,
                    interval_days INTEGER NOT NULL DEFAULT 1,
                    stage INTEGER NOT NULL DEFAULT 0,
                    ease INTEGER NOT NULL DEFAULT 3,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    # ------------------------------------------------------------ 知识点
    def add_topic(self, name: str, material: str = "") -> int:
        with self._lock:
            self._conn.execute(
                "INSERT INTO topics(name, material, created_at) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET material=excluded.material",
                (name.strip(), material.strip(), _now()),
            )
            row = self._conn.execute("SELECT id FROM topics WHERE name=?", (name.strip(),)).fetchone()
            self._conn.commit()
            return int(row["id"])

    def get_topic(self, key: str | int):
        with self._lock:
            if str(key).isdigit():
                row = self._conn.execute("SELECT * FROM topics WHERE id=?", (int(key),)).fetchone()
            else:
                row = self._conn.execute("SELECT * FROM topics WHERE name=?", (str(key),)).fetchone()
            return dict(row) if row else None

    def list_topics(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.id, t.name, length(t.material) AS chars, "
                "(SELECT COUNT(*) FROM questions q WHERE q.topic_id=t.id) AS questions "
                "FROM topics t ORDER BY t.id"
            ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------- 题目
    def add_question(self, topic_id: int, stem: str, answer: str, explain: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO questions(topic_id, stem, answer, explain, created_at) VALUES(?,?,?,?,?)",
                (topic_id, stem.strip(), answer.strip(), explain, _now()),
            )
            qid = int(cur.lastrowid)
            self._conn.execute(
                "INSERT INTO reviews(question_id, due_date, interval_days, stage, ease, updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(question_id) DO NOTHING",
                (qid, datetime.now().date().isoformat(), 1, 0, 3, _now()),
            )
            self._conn.commit()
            return qid

    def get_question(self, qid: int):
        with self._lock:
            row = self._conn.execute(
                "SELECT q.*, t.name AS topic FROM questions q JOIN topics t ON t.id=q.topic_id WHERE q.id=?",
                (qid,),
            ).fetchone()
            return dict(row) if row else None

    def list_questions(self, topic_id: int | None = None) -> list[dict]:
        with self._lock:
            if topic_id:
                rows = self._conn.execute(
                    "SELECT * FROM questions WHERE topic_id=? ORDER BY id", (topic_id,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------ 作答
    def add_attempt(self, question_id: int, user_answer: str, correct: bool) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO attempts(question_id, user_answer, correct, created_at) VALUES(?,?,?,?)",
                (question_id, user_answer.strip(), 1 if correct else 0, _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_attempts(self, question_id: int | None = None, limit: int = 20) -> list[dict]:
        with self._lock:
            if question_id:
                rows = self._conn.execute(
                    "SELECT * FROM attempts WHERE question_id=? ORDER BY id DESC", (question_id,)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT a.*, q.stem FROM attempts a JOIN questions q ON q.id=a.question_id "
                    "ORDER BY a.id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            t = self._conn.execute("SELECT COUNT(*) c FROM topics").fetchone()
            q = self._conn.execute("SELECT COUNT(*) c FROM questions").fetchone()
            a = self._conn.execute("SELECT COUNT(*) c, COALESCE(SUM(correct),0) ok FROM attempts").fetchone()
            return {"topics": t["c"], "questions": q["c"], "attempts": a["c"], "correct": a["ok"]}

    # ------------------------------------------------------------ 复习
    def set_review(self, question_id: int, due_date: str, interval_days: int, stage: int, ease: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO reviews(question_id, due_date, interval_days, stage, ease, updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET "
                "due_date=excluded.due_date, interval_days=excluded.interval_days, "
                "stage=excluded.stage, ease=excluded.ease, updated_at=excluded.updated_at",
                (question_id, due_date, interval_days, stage, ease, _now()),
            )
            self._conn.commit()

    def get_review(self, question_id: int):
        with self._lock:
            row = self._conn.execute("SELECT * FROM reviews WHERE question_id=?", (question_id,)).fetchone()
            return dict(row) if row else None

    def due_questions(self, today: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT q.id, q.stem, q.answer, t.name AS topic, r.due_date, r.stage "
                "FROM reviews r JOIN questions q ON q.id=r.question_id JOIN topics t ON t.id=q.topic_id "
                "WHERE r.due_date<=? ORDER BY r.due_date, q.id",
                (today,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_question(self, qid: int) -> bool:
        with self._lock:
            self._conn.execute("DELETE FROM reviews WHERE question_id=?", (qid,))
            self._conn.execute("DELETE FROM attempts WHERE question_id=?", (qid,))
            cur = self._conn.execute("DELETE FROM questions WHERE id=?", (qid,))
            self._conn.commit()
            return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
