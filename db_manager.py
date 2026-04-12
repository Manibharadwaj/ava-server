"""AVA Lead Database Manager"""
import sqlite3
from datetime import datetime

DB_FILE = "leads.db"

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
    conn.commit()
    conn.close()

def add_lead(phone, name=""):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO leads (phone, name) VALUES (?, ?)", (phone, name))
    conn.commit()
    conn.close()

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
    """Get all pending leads (for dashboard/bulk operations)."""
    conn = get_connection()
    leads = conn.execute("SELECT * FROM leads WHERE status = 'pending' ORDER BY id").fetchall()
    conn.close()
    return [dict(l) for l in leads]

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