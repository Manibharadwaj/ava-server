"""AVA Lead Database Manager"""
import sqlite3
from datetime import datetime

from config import DB_FILE

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE NOT NULL,
        name TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        call_count INTEGER DEFAULT 0,
        last_called TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS call_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER REFERENCES leads(id),
        call_id TEXT,
        started_at TEXT,
        ended_at TEXT,
        end_reason TEXT DEFAULT '',
        transcript TEXT DEFAULT ''
    )""")
    conn.commit()
    conn.close()

# ─── Leads ────────────────────────────────────

def add_lead(phone, name=""):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO leads (phone, name) VALUES (?, ?)", (phone, name))
    conn.commit()
    conn.close()

def add_leads_bulk(leads: list[dict]):
    conn = get_connection()
    count = 0
    for l in leads:
        phone = str(l.get("phone", "")).strip()
        name = str(l.get("name", "")).strip()
        if phone:
            conn.execute("INSERT OR IGNORE INTO leads (phone, name) VALUES (?, ?)", (phone, name))
            count += 1
    conn.commit()
    conn.close()
    return count

def add_leads_from_csv(filepath):
    import csv
    conn = get_connection()
    count = 0
    with open(filepath, "r") as f:
        for row in csv.DictReader(f):
            phone = row.get("phone", "").strip()
            name = row.get("name", "").strip()
            if phone:
                conn.execute("INSERT OR IGNORE INTO leads (phone, name) VALUES (?, ?)", (phone, name))
                count += 1
    conn.commit()
    conn.close()
    return count

def get_next_lead():
    conn = get_connection()
    lead = conn.execute("SELECT * FROM leads WHERE status = 'pending' ORDER BY id LIMIT 1").fetchone()
    conn.close()
    return dict(lead) if lead else None

def get_pending_leads():
    conn = get_connection()
    leads = conn.execute("SELECT * FROM leads WHERE status = 'pending' ORDER BY id").fetchall()
    conn.close()
    return [dict(l) for l in leads]

def get_all_leads(limit=100, offset=0):
    conn = get_connection()
    leads = conn.execute("SELECT * FROM leads ORDER BY id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    total = conn.execute("SELECT COUNT(*) as c FROM leads").fetchone()["c"]
    conn.close()
    return [dict(l) for l in leads], total

def delete_lead(lead_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()

def update_lead_status(phone, status, notes=""):
    conn = get_connection()
    conn.execute("""UPDATE leads SET status = ?, call_count = call_count + 1,
       last_called = ?, notes = ? WHERE phone = ?""",
       (status, datetime.now().isoformat(), notes, phone))
    conn.commit()
    conn.close()

def get_stats():
    conn = get_connection()
    stats = {}
    for row in conn.execute("SELECT status, COUNT(*) as count FROM leads GROUP BY status").fetchall():
        stats[row["status"]] = row["count"]
    conn.close()
    return stats

def get_lead_by_phone(phone):
    conn = get_connection()
    lead = conn.execute("SELECT * FROM leads WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return dict(lead) if lead else None

# ─── Call Logs ────────────────────────────────

def add_call_log(lead_id, call_id, transcript=""):
    conn = get_connection()
    conn.execute("""INSERT INTO call_logs (lead_id, call_id, started_at, transcript)
        VALUES (?, ?, ?, ?)""", (lead_id, call_id, datetime.now().isoformat(), transcript))
    conn.commit()
    conn.close()

def end_call_log(call_id, reason, transcript=""):
    conn = get_connection()
    conn.execute("""UPDATE call_logs SET ended_at = ?, end_reason = ?, transcript = ?
        WHERE call_id = ?""", (datetime.now().isoformat(), reason, transcript, call_id))
    conn.commit()
    conn.close()

def get_call_logs(limit=50, offset=0):
    conn = get_connection()
    logs = conn.execute("""
        SELECT cl.*, l.phone, l.name FROM call_logs cl
        LEFT JOIN leads l ON cl.lead_id = l.id
        ORDER BY cl.started_at DESC LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    conn.close()
    return [dict(l) for l in logs]