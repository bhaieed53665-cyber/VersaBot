"""
سكربت لمرة واحدة: ينقل كل البيانات الموجودة بملف SQLite القديم
(subscriptions.db) إلى قاعدة PostgreSQL الجديدة.

الاستخدام:
    1) ضيف DATABASE_URL بملف .env (شوف تعليمات config.py).
    2) شغّل مرة وحدة: python migrate_sqlite_to_postgres.py
    3) بعدها احذف/أرشف ملف subscriptions.db القديم.

ملاحظة: السكربت idempotent تقريباً بفضل ON CONFLICT DO NOTHING،
فممكن تشغله أكتر من مرة بدون تكرار للبيانات.
"""

import sqlite3

import psycopg2

import config
import database  # يشغّل init_db() على PostgreSQL قبل النقل

SQLITE_PATH = config.DB_PATH  # نفس المسار القديم (افتراضياً subscriptions.db)


def migrate():
    database.init_db()  # تأكد إن الجداول موجودة بالـ PostgreSQL

    sq_conn = sqlite3.connect(SQLITE_PATH)
    sq_conn.row_factory = sqlite3.Row
    sq_cursor = sq_conn.cursor()

    pg_conn = psycopg2.connect(config.DATABASE_URL)
    pg_cursor = pg_conn.cursor()

    # ---- subs ----
    sq_cursor.execute("SELECT * FROM subs")
    subs_rows = sq_cursor.fetchall()
    for row in subs_rows:
        pg_cursor.execute('''
            INSERT INTO subs (user_id, guild_id, role_id, end_date, dm_message_id, log_message_id, start_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, guild_id, role_id) DO NOTHING
        ''', (row["user_id"], row["guild_id"], row["role_id"], row["end_date"],
              row["dm_message_id"], row["log_message_id"], row["start_date"]))
    print(f"تم نقل {len(subs_rows)} صف من جدول subs")

    # ---- shared_members ----
    sq_cursor.execute("SELECT * FROM shared_members")
    shared_rows = sq_cursor.fetchall()
    for row in shared_rows:
        pg_cursor.execute('''
            INSERT INTO shared_members (owner_id, guild_id, role_id, member_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (owner_id, guild_id, role_id, member_id) DO NOTHING
        ''', (row["owner_id"], row["guild_id"], row["role_id"], row["member_id"]))
    print(f"تم نقل {len(shared_rows)} صف من جدول shared_members")

    # ---- audit_log ----
    sq_cursor.execute("SELECT * FROM audit_log")
    audit_rows = sq_cursor.fetchall()
    for row in audit_rows:
        pg_cursor.execute('''
            INSERT INTO audit_log (guild_id, actor_id, actor_name, action, target_id, role_id, details, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (row["guild_id"], row["actor_id"], row["actor_name"], row["action"],
              row["target_id"], row["role_id"], row["details"], row["created_at"]))
    print(f"تم نقل {len(audit_rows)} صف من جدول audit_log")

    pg_conn.commit()
    pg_cursor.close()
    pg_conn.close()
    sq_conn.close()
    print("اكتملت الهجرة بنجاح ✅")


if __name__ == "__main__":
    migrate()
