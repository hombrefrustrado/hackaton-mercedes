import sqlite3
import os
import time
import logging
from .config import DB_FILE, PRICING

logger = logging.getLogger("finops_proxy.database")

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Create Roles Table (Cost Centers with budget limits)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS roles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        spent REAL DEFAULT 0.0,
        budget_limit REAL DEFAULT 5.0,
        alert_threshold REAL DEFAULT 0.8,
        alert_fired INTEGER DEFAULT 0
    )
    """)
    
    # 2. Create Users Table (Linked to a Role)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        role_id TEXT NOT NULL,
        FOREIGN KEY (role_id) REFERENCES roles (id)
    )
    """)
    
    # 3. Create Transactions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        user_id TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL,
        completion_tokens INTEGER NOT NULL,
        cost REAL NOT NULL,
        latency_ms INTEGER NOT NULL,
        stream INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)
    
    # 4. Create Alerts Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        role_id TEXT NOT NULL,
        message TEXT NOT NULL,
        severity TEXT NOT NULL,
        FOREIGN KEY (role_id) REFERENCES roles (id)
    )
    """)
    
    # Seed default roles if empty
    cursor.execute("SELECT COUNT(*) FROM roles")
    if cursor.fetchone()[0] == 0:
        default_roles = [
            ("marketing", "Marketing", 0.0, 5.0, 0.8, 0),
            ("producto", "Producto", 0.0, 10.0, 0.8, 0),
            ("general", "General", 0.0, 2.0, 0.8, 0)
        ]
        cursor.executemany("INSERT INTO roles VALUES (?, ?, ?, ?, ?, ?)", default_roles)
        
    # Seed default users linked to roles if empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ("ana", "Ana", "marketing"),
            ("carlos", "Carlos", "producto"),
            ("default", "Usuario Genérico", "general")
        ]
        cursor.executemany("INSERT INTO users VALUES (?, ?, ?)", default_users)
        
    conn.commit()
    conn.close()
    logger.info("SQLite database initialized with separate Roles and Users tables.")

# Initialize database on module load
init_db()

def get_state():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Retrieve roles (for budget limits dashboard display)
    cursor.execute("SELECT * FROM roles")
    consumers = {}
    for r in cursor.fetchall():
        consumers[r["id"]] = {
            "name": r["name"],
            "spent": r["spent"],
            "budget_limit": r["budget_limit"],
            "alert_threshold": r["alert_threshold"],
            "alert_fired": bool(r["alert_fired"])
        }
        
    # Retrieve transactions with user & role joining
    cursor.execute("""
        SELECT t.*, u.name as user_name, r.name as role_name 
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN roles r ON u.role_id = r.id
        ORDER BY t.timestamp ASC
    """)
    transactions = []
    for r in cursor.fetchall():
        transactions.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "consumer_id": r["user_id"],
            "consumer_name": f"{r['user_name']} ({r['role_name']})",
            "model": r["model"],
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "cost": r["cost"],
            "latency_ms": r["latency_ms"],
            "stream": bool(r["stream"])
        })
        
    # Retrieve alerts
    cursor.execute("SELECT * FROM alerts ORDER BY timestamp ASC")
    alerts = []
    for r in cursor.fetchall():
        alerts.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "consumer_id": r["role_id"],
            "consumer_name": r["role_id"].title(),
            "message": r["message"],
            "severity": r["severity"]
        })
        
    conn.close()
    return {
        "consumers": consumers, # Mapped to roles for backward compatibility with UI
        "transactions": transactions,
        "alerts": alerts
    }

def update_consumer_config(data: dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    for role_id, config in data.items():
        if "budget_limit" in config:
            cursor.execute("UPDATE roles SET budget_limit = ? WHERE id = ?", (float(config["budget_limit"]), role_id))
        if "alert_threshold" in config:
            cursor.execute("UPDATE roles SET alert_threshold = ? WHERE id = ?", (float(config["alert_threshold"]), role_id))
            
        # Reset alert_fired if limit increased above current spend
        cursor.execute("SELECT spent, budget_limit, alert_threshold FROM roles WHERE id = ?", (role_id,))
        row = cursor.fetchone()
        if row:
            spent, limit, threshold = row["spent"], row["budget_limit"], row["alert_threshold"]
            if spent < (limit * threshold):
                cursor.execute("UPDATE roles SET alert_fired = 0 WHERE id = ?", (role_id,))
                
    conn.commit()
    conn.close()
    return get_state()

def reset_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transactions")
    cursor.execute("DELETE FROM alerts")
    cursor.execute("UPDATE roles SET spent = 0.0, alert_fired = 0")
    conn.commit()
    conn.close()
    return get_state()

def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost = (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000
    return cost

def record_transaction(user_id: str, model: str, prompt_tokens: int, completion_tokens: int, cost: float, latency: float, stream: bool = False):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Ensure user exists, if not create linked to general role
    cursor.execute("SELECT role_id FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT OR IGNORE INTO users (id, name, role_id) VALUES (?, ?, 'general')", (user_id, user_id.title()))
        role_id = 'general'
    else:
        role_id = row["role_id"]
        
    # 2. Update role spent
    cursor.execute("UPDATE roles SET spent = spent + ? WHERE id = ?", (cost, role_id))
    
    # 3. Read updated role details
    cursor.execute("SELECT name, spent, budget_limit, alert_threshold, alert_fired FROM roles WHERE id = ?", (role_id,))
    role_row = cursor.fetchone()
    role_name, spent, limit, threshold, alert_fired = role_row["name"], role_row["spent"], role_row["budget_limit"], role_row["alert_threshold"], role_row["alert_fired"]
    
    # 4. Insert transaction
    tx_id = f"tx_{int(time.time() * 1000)}"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tx_id, timestamp, user_id, model, prompt_tokens, completion_tokens, cost, int(latency * 1000), int(stream))
    )
    
    # 5. Check and fire alerts on role/team budget
    if spent >= (limit * threshold) and not alert_fired:
        cursor.execute("UPDATE roles SET alert_fired = 1 WHERE id = ?", (role_id,))
        alert_id = f"alert_{int(time.time() * 1000)}"
        message = f"¡Alerta de Gasto! El rol '{role_name}' ha superado el {int(threshold * 100)}% de su límite (${spent:.4f} / ${limit:.2f})"
        cursor.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?)", (alert_id, timestamp, role_id, message, "warning"))
        
    if spent >= limit:
        alert_id = f"alert_limit_{int(time.time() * 1000)}"
        message = f"¡LÍMITE EXCEDIDO! El rol '{role_name}' ha agotado su presupuesto (${spent:.4f} / ${limit:.2f})"
        cursor.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?)", (alert_id, timestamp, role_id, message, "danger"))
        
    conn.commit()
    conn.close()
