"""
كل التعامل مع قاعدة البيانات يمر من هذا الملف فقط.
- اتصال واحد موحّد مع تفعيل WAL mode لمنع مشاكل القفل (database is locked)
  عند وجود عمليات متزامنة (المهمة الدورية + تفاعل عدة أعضاء بنفس الوقت).
- كل الدوال sync عادية وتُستدعى عبر asyncio.to_thread من الأكواج.
"""
import sqlite3
import datetime
import contextlib

import config

MAX_SHARED_MEMBERS = config.MAX_SHARED_MEMBERS


@contextlib.contextmanager
def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        # WAL يسمح بقراءة وكتابة متزامنة بدون قفل كامل لقاعدة البيانات
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subs (
                user_id INTEGER,
                guild_id INTEGER,
                role_id INTEGER,
                end_date TEXT,
                dm_message_id INTEGER,
                log_message_id INTEGER,
                start_date TEXT,
                PRIMARY KEY (user_id, guild_id, role_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shared_members (
                owner_id INTEGER,
                guild_id INTEGER,
                role_id INTEGER,
                member_id INTEGER,
                PRIMARY KEY (owner_id, guild_id, role_id, member_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                actor_id INTEGER,
                actor_name TEXT,
                action TEXT,
                target_id INTEGER,
                role_id INTEGER,
                details TEXT,
                created_at TEXT
            )
        ''')

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_guild ON audit_log (guild_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log (target_id)")


# ---------------------------------------------------------------------------
# اشتراكات (subs)
# ---------------------------------------------------------------------------

def save_sub(user_id, guild_id, role_id, end_date_str, dm_msg_id, log_msg_id, start_date_str):
    with get_connection() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO subs
            (user_id, guild_id, role_id, end_date, dm_message_id, log_message_id, start_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, guild_id, role_id, end_date_str, dm_msg_id, log_msg_id, start_date_str))


def get_and_delete_sub(user_id, guild_id, role_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT dm_message_id, log_message_id FROM subs WHERE user_id = ? AND guild_id = ? AND role_id = ?',
            (user_id, guild_id, role_id)
        )
        row = cursor.fetchone()
        cursor.execute(
            'DELETE FROM subs WHERE user_id = ? AND guild_id = ? AND role_id = ?',
            (user_id, guild_id, role_id)
        )
        return row


def get_guild_subs(guild_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, role_id, end_date FROM subs WHERE guild_id = ?', (guild_id,))
        return cursor.fetchall()


def get_expired_subs(now_str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT user_id, guild_id, role_id, dm_message_id, log_message_id FROM subs WHERE end_date <= ?',
            (now_str,)
        )
        return cursor.fetchall()


def delete_subs_bulk(rows):
    if not rows:
        return
    with get_connection() as conn:
        conn.executemany(
            'DELETE FROM subs WHERE user_id = ? AND guild_id = ? AND role_id = ?', rows
        )


def get_owner_role_ids(guild_id, user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT role_id FROM subs WHERE user_id = ? AND guild_id = ?', (user_id, guild_id))
        return [row[0] for row in cursor.fetchall()]


def get_owner_sub_info(guild_id, user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT role_id, start_date, end_date FROM subs WHERE user_id = ? AND guild_id = ?',
            (user_id, guild_id)
        )
        return cursor.fetchall()


# ---------------------------------------------------------------------------
# الأعضاء المشاركون على الرتبة (shared_members)
# ---------------------------------------------------------------------------

def get_shared_members(owner_id, guild_id, role_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT member_id FROM shared_members WHERE owner_id = ? AND guild_id = ? AND role_id = ?',
            (owner_id, guild_id, role_id)
        )
        return [row[0] for row in cursor.fetchall()]


def check_shared_member_slot(owner_id, guild_id, role_id, target_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM shared_members WHERE owner_id = ? AND guild_id = ? AND role_id = ?',
            (owner_id, guild_id, role_id)
        )
        count = cursor.fetchone()[0]
        cursor.execute(
            'SELECT 1 FROM shared_members WHERE owner_id = ? AND guild_id = ? AND role_id = ? AND member_id = ?',
            (owner_id, guild_id, role_id, target_id)
        )
        already_added = cursor.fetchone() is not None
        return count, already_added


def add_shared_member(owner_id, guild_id, role_id, target_id):
    with get_connection() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO shared_members (owner_id, guild_id, role_id, member_id) VALUES (?, ?, ?, ?)',
            (owner_id, guild_id, role_id, target_id)
        )


def remove_shared_member(owner_id, guild_id, role_id, target_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM shared_members WHERE owner_id = ? AND guild_id = ? AND role_id = ? AND member_id = ?',
            (owner_id, guild_id, role_id, target_id)
        )
        exists = cursor.fetchone() is not None
        if exists:
            cursor.execute(
                'DELETE FROM shared_members WHERE owner_id = ? AND guild_id = ? AND role_id = ? AND member_id = ?',
                (owner_id, guild_id, role_id, target_id)
            )
        return exists


def delete_shared_members_for_role(owner_id, guild_id, role_id):
    with get_connection() as conn:
        conn.execute(
            'DELETE FROM shared_members WHERE owner_id = ? AND guild_id = ? AND role_id = ?',
            (owner_id, guild_id, role_id)
        )


# ---------------------------------------------------------------------------
# سجل التدقيق (audit_log)
# ---------------------------------------------------------------------------

def insert_audit_log(guild_id, actor_id, actor_name, action, target_id=None, role_id=None, details=None):
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    with get_connection() as conn:
        conn.execute('''
            INSERT INTO audit_log (guild_id, actor_id, actor_name, action, target_id, role_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (guild_id, actor_id, actor_name, action, target_id, role_id, details, now_str))


def get_audit_log(guild_id, member_id=None, limit=10, offset=0):
    with get_connection() as conn:
        cursor = conn.cursor()
        if member_id:
            cursor.execute('''
                SELECT actor_id, actor_name, action, target_id, role_id, details, created_at
                FROM audit_log
                WHERE guild_id = ? AND (actor_id = ? OR target_id = ?)
                ORDER BY id DESC LIMIT ? OFFSET ?
            ''', (guild_id, member_id, member_id, limit, offset))
        else:
            cursor.execute('''
                SELECT actor_id, actor_name, action, target_id, role_id, details, created_at
                FROM audit_log
                WHERE guild_id = ?
                ORDER BY id DESC LIMIT ? OFFSET ?
            ''', (guild_id, limit, offset))
        return cursor.fetchall()


def count_audit_log(guild_id, member_id=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        if member_id:
            cursor.execute(
                'SELECT COUNT(*) FROM audit_log WHERE guild_id = ? AND (actor_id = ? OR target_id = ?)',
                (guild_id, member_id, member_id)
            )
        else:
            cursor.execute('SELECT COUNT(*) FROM audit_log WHERE guild_id = ?', (guild_id,))
        return cursor.fetchone()[0]
