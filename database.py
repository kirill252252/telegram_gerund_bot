"""
database.py — all DB access for the vocabulary bot.
Import everything from here; never open bot_data.db elsewhere.
"""

import sqlite3
import logging
from datetime import date, timedelta
from threading import Lock

DB_PATH = "bot_data.db"
_lock = Lock()          # one writer at a time


# ─────────────────────────────────────────────
# LOW-LEVEL HELPERS
# ─────────────────────────────────────────────

def _conn():
    """Return a connection with row_factory so columns are accessible by name."""
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                uid                 INTEGER PRIMARY KEY,
                total_score         INTEGER DEFAULT 0,
                translate_score     INTEGER DEFAULT 0,
                ger_inf_score       INTEGER DEFAULT 0,
                quiz_score          INTEGER DEFAULT 0,
                irregular_score     INTEGER DEFAULT 0,
                xp                  INTEGER DEFAULT 0,
                level               INTEGER DEFAULT 1,
                best_streak         INTEGER DEFAULT 0,
                last_active_date    TEXT    DEFAULT '',
                daily_streak        INTEGER DEFAULT 0,
                nickname            TEXT    DEFAULT '',
                best_time_attack    INTEGER DEFAULT 0,
                reminder_time       TEXT    DEFAULT '',
                weekly_score        INTEGER DEFAULT 0,
                weekly_reset_date   TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS mistakes (
                uid         INTEGER,
                verb        TEXT,
                wrong_count INTEGER DEFAULT 1,
                PRIMARY KEY (uid, verb)
            );

            CREATE TABLE IF NOT EXISTS achievements (
                uid         INTEGER,
                achievement TEXT,
                earned_at   TEXT,
                PRIMARY KEY (uid, achievement)
            );

            CREATE TABLE IF NOT EXISTS daily_scores (
                uid         INTEGER,
                score_date  TEXT,
                score       INTEGER DEFAULT 0,
                PRIMARY KEY (uid, score_date)
            );
        ''')
        con.commit()

        # Non-destructive column migrations
        _safe_alters = [
            "ALTER TABLE users ADD COLUMN nickname TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN best_time_attack INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN reminder_time TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN weekly_score INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN weekly_reset_date TEXT DEFAULT ''",
        ]
        for sql in _safe_alters:
            try:
                cur.execute(sql)
                con.commit()
            except sqlite3.OperationalError:
                pass
        con.close()


# ─────────────────────────────────────────────
# USER CRUD
# ─────────────────────────────────────────────

def db_ensure(uid: int):
    with _lock:
        con = _conn()
        con.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
        con.commit()
        con.close()


def db_get(uid: int) -> sqlite3.Row | None:
    """Return the full users row for uid (as a Row, accessible by column name)."""
    db_ensure(uid)
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE uid=?", (uid,))
        row = cur.fetchone()
        con.close()
    return row


def db_add_score(uid: int, *, total=0, translate=0, ger_inf=0, quiz=0,
                 irregular=0, xp=0) -> int | None:
    """
    Add scores and XP, update weekly counter, track daily score.
    Returns the new level if it changed, else None.
    """
    db_ensure(uid)
    today = str(date.today())
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute('''
            UPDATE users SET
                total_score     = total_score     + :total,
                translate_score = translate_score + :translate,
                ger_inf_score   = ger_inf_score   + :ger_inf,
                quiz_score      = quiz_score      + :quiz,
                irregular_score = irregular_score + :irregular,
                xp              = xp              + :xp,
                weekly_score    = weekly_score    + :total
            WHERE uid = :uid
        ''', dict(total=total, translate=translate, ger_inf=ger_inf,
                  quiz=quiz, irregular=irregular, xp=xp, uid=uid))

        cur.execute('''
            INSERT INTO daily_scores (uid, score_date, score) VALUES (?, ?, ?)
            ON CONFLICT(uid, score_date) DO UPDATE SET score = score + excluded.score
        ''', (uid, today, total))

        cur.execute("SELECT xp, level FROM users WHERE uid=?", (uid,))
        row = cur.fetchone()
        new_level = None
        if row:
            calc = 1 + row["xp"] // 100
            if calc != row["level"]:
                cur.execute("UPDATE users SET level=? WHERE uid=?", (calc, uid))
                new_level = calc
        con.commit()
        con.close()
    return new_level


def db_update_best_streak(uid: int, streak: int):
    db_ensure(uid)
    with _lock:
        con = _conn()
        con.execute(
            "UPDATE users SET best_streak = MAX(best_streak, ?) WHERE uid=?",
            (streak, uid)
        )
        con.commit()
        con.close()


def db_update_best_ta(uid: int, score: int):
    db_ensure(uid)
    with _lock:
        con = _conn()
        con.execute(
            "UPDATE users SET best_time_attack = MAX(best_time_attack, ?) WHERE uid=?",
            (score, uid)
        )
        con.commit()
        con.close()


def db_update_daily(uid: int) -> int:
    """Update daily streak; return the new streak value."""
    db_ensure(uid)
    today = str(date.today())
    yesterday = str(date.today() - timedelta(days=1))
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT last_active_date, daily_streak FROM users WHERE uid=?", (uid,))
        row = cur.fetchone()
        if row and row["last_active_date"] == today:
            streak = row["daily_streak"]
            con.close()
            return streak
        streak = (row["daily_streak"] + 1
                  if row and row["last_active_date"] == yesterday else 1)
        cur.execute(
            "UPDATE users SET last_active_date=?, daily_streak=? WHERE uid=?",
            (today, streak, uid)
        )
        con.commit()
        con.close()
    return streak


def db_reset_weekly_if_needed(uid: int):
    db_ensure(uid)
    today = date.today()
    monday = str(today - timedelta(days=today.weekday()))
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT weekly_reset_date FROM users WHERE uid=?", (uid,))
        row = cur.fetchone()
        if row and row["weekly_reset_date"] != monday:
            cur.execute(
                "UPDATE users SET weekly_score=0, weekly_reset_date=? WHERE uid=?",
                (monday, uid)
            )
            con.commit()
        con.close()


def db_set_nickname(uid: int, nickname: str):
    db_ensure(uid)
    with _lock:
        con = _conn()
        con.execute("UPDATE users SET nickname=? WHERE uid=?", (nickname, uid))
        con.commit()
        con.close()


def db_get_nickname(uid: int) -> str | None:
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT nickname FROM users WHERE uid=?", (uid,))
        row = cur.fetchone()
        con.close()
    return row["nickname"] if row and row["nickname"] else None


def db_set_reminder(uid: int, time_str: str):
    db_ensure(uid)
    with _lock:
        con = _conn()
        con.execute("UPDATE users SET reminder_time=? WHERE uid=?", (time_str, uid))
        con.commit()
        con.close()


def db_get_all_reminders() -> list[tuple]:
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT uid, reminder_time FROM users WHERE reminder_time != ''")
        rows = [(r["uid"], r["reminder_time"]) for r in cur.fetchall()]
        con.close()
    return rows


def db_get_all_users() -> list[int]:
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT uid FROM users")
        rows = [r["uid"] for r in cur.fetchall()]
        con.close()
    return rows


def db_leaderboard(limit: int = 10, weekly: bool = False) -> list[tuple]:
    col = "weekly_score" if weekly else "total_score"
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute(
            f"SELECT uid, {col}, level FROM users ORDER BY {col} DESC LIMIT ?",
            (limit,)
        )
        rows = [(r["uid"], r[col], r["level"]) for r in cur.fetchall()]
        con.close()
    return rows


def db_get_daily_scores(uid: int, days: int = 7) -> list[tuple]:
    dates = [str(date.today() - timedelta(days=i)) for i in range(days - 1, -1, -1)]
    result = []
    with _lock:
        con = _conn()
        cur = con.cursor()
        for d in dates:
            cur.execute(
                "SELECT score FROM daily_scores WHERE uid=? AND score_date=?",
                (uid, d)
            )
            r = cur.fetchone()
            result.append((d, r["score"] if r else 0))
        con.close()
    return result


# ─────────────────────────────────────────────
# MISTAKES
# ─────────────────────────────────────────────

def db_add_mistake(uid: int, verb: str):
    db_ensure(uid)
    with _lock:
        con = _conn()
        con.execute('''
            INSERT INTO mistakes (uid, verb, wrong_count) VALUES (?, ?, 1)
            ON CONFLICT(uid, verb) DO UPDATE SET wrong_count = wrong_count + 1
        ''', (uid, verb))
        con.commit()
        con.close()


def db_get_mistakes(uid: int, limit: int = 10) -> list[tuple]:
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute(
            "SELECT verb, wrong_count FROM mistakes WHERE uid=? ORDER BY wrong_count DESC LIMIT ?",
            (uid, limit)
        )
        rows = [(r["verb"], r["wrong_count"]) for r in cur.fetchall()]
        con.close()
    return rows


def db_get_global_top_mistakes(limit: int = 10) -> list[tuple]:
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute('''
            SELECT verb, SUM(wrong_count) AS total
            FROM mistakes
            GROUP BY verb
            ORDER BY total DESC
            LIMIT ?
        ''', (limit,))
        rows = [(r["verb"], r["total"]) for r in cur.fetchall()]
        con.close()
    return rows


# ─────────────────────────────────────────────
# ACHIEVEMENTS
# ─────────────────────────────────────────────

def db_give_achievement(uid: int, key: str) -> bool:
    """Returns True if this is a NEW achievement."""
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM achievements WHERE uid=? AND achievement=?",
            (uid, key)
        )
        exists = cur.fetchone()
        if not exists:
            cur.execute(
                "INSERT INTO achievements (uid, achievement, earned_at) VALUES (?,?,?)",
                (uid, key, str(date.today()))
            )
            con.commit()
            con.close()
            return True
        con.close()
    return False


def db_get_achievements(uid: int) -> list[str]:
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT achievement FROM achievements WHERE uid=?", (uid,))
        rows = [r["achievement"] for r in cur.fetchall()]
        con.close()
    return rows


# ─────────────────────────────────────────────
# ADMIN / EXPORT
# ─────────────────────────────────────────────

def db_export_path() -> str:
    """Return the path to the database file (for sending as a document)."""
    return DB_PATH


def db_stats_summary() -> dict:
    """Return a dict of high-level stats for the admin panel."""
    with _lock:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM users")
        users = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM achievements")
        ach = cur.fetchone()["cnt"]

        cur.execute("SELECT SUM(wrong_count) AS total FROM mistakes")
        row = cur.fetchone()
        mistakes_total = row["total"] or 0

        top_mistakes = db_get_global_top_mistakes(10)   # re-uses same lock — would deadlock!
        con.close()

    # Re-query top mistakes outside the lock to avoid the re-entrant deadlock
    top_mistakes = db_get_global_top_mistakes(10)
    return {
        "users": users,
        "achievements": ach,
        "mistakes_total": mistakes_total,
        "top_mistakes": top_mistakes,
    }
