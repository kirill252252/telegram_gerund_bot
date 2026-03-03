import sqlite3
import csv
import io
from datetime import date, timedelta
from typing import Optional

DB_PATH = "bot_data.db"

# ─────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────

def init_users_table():
    """Create users table and run migrations if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            uid                 INTEGER PRIMARY KEY,
            username            TEXT    DEFAULT '',
            first_name          TEXT    DEFAULT '',
            last_name           TEXT    DEFAULT '',
            nickname            TEXT    DEFAULT '',
            language_code       TEXT    DEFAULT 'ru',
            registered_at       TEXT    DEFAULT '',

            total_score         INTEGER DEFAULT 0,
            translate_score     INTEGER DEFAULT 0,
            ger_inf_score       INTEGER DEFAULT 0,
            quiz_score          INTEGER DEFAULT 0,
            irregular_score     INTEGER DEFAULT 0,

            xp                  INTEGER DEFAULT 0,
            level               INTEGER DEFAULT 1,
            best_streak         INTEGER DEFAULT 0,
            best_time_attack    INTEGER DEFAULT 0,

            daily_streak        INTEGER DEFAULT 0,
            last_active_date    TEXT    DEFAULT '',
            weekly_score        INTEGER DEFAULT 0,
            weekly_reset_date   TEXT    DEFAULT '',

            reminder_time       TEXT    DEFAULT '',
            is_banned           INTEGER DEFAULT 0,
            ban_reason          TEXT    DEFAULT ''
        )
    ''')

    migrations = [
        "ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN last_name TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN language_code TEXT DEFAULT 'ru'",
        "ALTER TABLE users ADD COLUMN registered_at TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN ban_reason TEXT DEFAULT ''",
    ]
    for m in migrations:
        try:
            c.execute(m)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


init_users_table()


# ─────────────────────────────────────────────
# CREATE / ENSURE
# ─────────────────────────────────────────────

def user_ensure(uid: int, username: str = '', first_name: str = '', last_name: str = '', language_code: str = 'ru'):
    """
    Insert user if not exists, update name fields if they changed.
    Call this on every incoming message.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    today = str(date.today())
    c.execute("SELECT uid FROM users WHERE uid = ?", (uid,))
    exists = c.fetchone()

    if not exists:
        c.execute('''
            INSERT INTO users (uid, username, first_name, last_name, language_code, registered_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (uid, username, first_name, last_name, language_code, today))
    else:
        # Keep name fields fresh in case user changes their Telegram name
        c.execute('''
            UPDATE users
            SET username = ?, first_name = ?, last_name = ?, language_code = ?
            WHERE uid = ?
        ''', (username, first_name, last_name, language_code, uid))

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────

def user_get(uid: int) -> Optional[sqlite3.Row]:
    """Return a Row object for the user (access fields by name), or None."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    row = c.fetchone()
    conn.close()
    return row


def user_get_all(banned: Optional[bool] = None) -> list:
    """
    Return all users as a list of Row objects.
    banned=True  → only banned users
    banned=False → only active users
    banned=None  → all users
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if banned is None:
        c.execute("SELECT * FROM users ORDER BY total_score DESC")
    else:
        c.execute("SELECT * FROM users WHERE is_banned = ? ORDER BY total_score DESC",
                  (1 if banned else 0,))

    rows = c.fetchall()
    conn.close()
    return rows


def user_search(query: str) -> list:
    """Search users by uid, username, first_name, last_name, or nickname."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    like = f"%{query}%"
    c.execute('''
        SELECT * FROM users
        WHERE CAST(uid AS TEXT) LIKE ?
           OR username    LIKE ?
           OR first_name  LIKE ?
           OR last_name   LIKE ?
           OR nickname    LIKE ?
        ORDER BY total_score DESC
    ''', (like, like, like, like, like))
    rows = c.fetchall()
    conn.close()
    return rows


def user_get_all_uids() -> list[int]:
    """Return list of all user IDs (for broadcasting)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT uid FROM users WHERE is_banned = 0")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def user_count() -> dict:
    """Return stats: total, active today, active this week, banned."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = str(date.today())
    week_ago = str(date.today() - timedelta(days=7))

    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE last_active_date = ?", (today,))
    active_today = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE last_active_date >= ?", (week_ago,))
    active_week = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    banned = c.fetchone()[0]

    conn.close()
    return {
        "total": total,
        "active_today": active_today,
        "active_week": active_week,
        "banned": banned,
    }


# ─────────────────────────────────────────────
# UPDATE
# ─────────────────────────────────────────────

def user_set_nickname(uid: int, nickname: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET nickname = ? WHERE uid = ?", (nickname, uid))
    conn.commit()
    conn.close()


def user_set_reminder(uid: int, time_str: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET reminder_time = ? WHERE uid = ?", (time_str, uid))
    conn.commit()
    conn.close()


def user_add_score(uid: int, total=0, translate=0, ger_inf=0, quiz=0, irregular=0, xp=0) -> Optional[int]:
    """
    Add scores and XP. Returns new level if leveled up, else None.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = str(date.today())

    c.execute('''
        UPDATE users SET
            total_score     = total_score     + ?,
            translate_score = translate_score + ?,
            ger_inf_score   = ger_inf_score   + ?,
            quiz_score      = quiz_score      + ?,
            irregular_score = irregular_score + ?,
            xp              = xp              + ?,
            weekly_score    = weekly_score    + ?
        WHERE uid = ?
    ''', (total, translate, ger_inf, quiz, irregular, xp, total, uid))

    # Track daily score
    c.execute('''
        INSERT INTO daily_scores (uid, score_date, score) VALUES (?, ?, ?)
        ON CONFLICT(uid, score_date) DO UPDATE SET score = score + ?
    ''', (uid, today, total, total))

    # Level up check
    c.execute("SELECT xp, level FROM users WHERE uid = ?", (uid,))
    row = c.fetchone()
    new_level = None
    if row:
        xp_total, level = row
        calc = 1 + xp_total // 100
        if calc != level:
            c.execute("UPDATE users SET level = ? WHERE uid = ?", (calc, uid))
            new_level = calc

    conn.commit()
    conn.close()
    return new_level


def user_update_streak(uid: int) -> int:
    """Update daily login streak. Returns current streak count."""
    today = str(date.today())
    yesterday = str(date.today() - timedelta(days=1))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_active_date, daily_streak FROM users WHERE uid = ?", (uid,))
    row = c.fetchone()
    streak = 1
    if row:
        last, ds = row
        if last == today:
            conn.close()
            return ds
        streak = ds + 1 if last == yesterday else 1
    c.execute("UPDATE users SET last_active_date = ?, daily_streak = ? WHERE uid = ?",
              (today, streak, uid))
    conn.commit()
    conn.close()
    return streak


def user_update_best_streak(uid: int, streak: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET best_streak = MAX(best_streak, ?) WHERE uid = ?", (streak, uid))
    conn.commit()
    conn.close()


def user_update_best_ta(uid: int, score: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET best_time_attack = MAX(best_time_attack, ?) WHERE uid = ?",
                 (score, uid))
    conn.commit()
    conn.close()


def user_reset_weekly_if_needed(uid: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT weekly_reset_date FROM users WHERE uid = ?", (uid,))
    row = c.fetchone()
    today = date.today()
    monday = str(today - timedelta(days=today.weekday()))
    if row and row[0] != monday:
        c.execute("UPDATE users SET weekly_score = 0, weekly_reset_date = ? WHERE uid = ?",
                  (monday, uid))
        conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# BAN / UNBAN
# ─────────────────────────────────────────────

def user_ban(uid: int, reason: str = ''):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET is_banned = 1, ban_reason = ? WHERE uid = ?", (reason, uid))
    conn.commit()
    conn.close()


def user_unban(uid: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET is_banned = 0, ban_reason = '' WHERE uid = ?", (uid,))
    conn.commit()
    conn.close()


def user_is_banned(uid: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE uid = ?", (uid,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0])


# ─────────────────────────────────────────────
# DELETE
# ─────────────────────────────────────────────

def user_delete(uid: int):
    """Fully remove a user and all their data."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE uid = ?", (uid,))
    c.execute("DELETE FROM mistakes WHERE uid = ?", (uid,))
    c.execute("DELETE FROM achievements WHERE uid = ?", (uid,))
    c.execute("DELETE FROM daily_scores WHERE uid = ?", (uid,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# LEADERBOARD
# ─────────────────────────────────────────────

def user_leaderboard(limit: int = 10, weekly: bool = False) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    col = "weekly_score" if weekly else "total_score"
    c.execute(f'''
        SELECT uid, nickname, first_name, username, {col} as score, level
        FROM users
        WHERE is_banned = 0
        ORDER BY {col} DESC
        LIMIT ?
    ''', (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


# ─────────────────────────────────────────────
# REMINDERS
# ─────────────────────────────────────────────

def user_get_all_reminders() -> list[tuple]:
    """Return [(uid, reminder_time), ...] for all users with a reminder set."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT uid, reminder_time FROM users WHERE reminder_time != '' AND is_banned = 0")
    rows = c.fetchall()
    conn.close()
    return rows


# ─────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────

def user_export_csv() -> str:
    """Return all users as a CSV string."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY total_score DESC")
    rows = c.fetchall()
    conn.close()

    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    return output.getvalue()


# ─────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────

def user_display_name(row) -> str:
    """
    Returns the best available display name for a user row.
    Priority: nickname → first_name → @username → 'User {uid}'
    """
    if row['nickname']:
        return row['nickname']
    if row['first_name']:
        return row['first_name']
    if row['username']:
        return f"@{row['username']}"
    return f"User {row['uid']}"