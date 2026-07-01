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
    
    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS consumers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        spent REAL DEFAULT 0.0,
        budget_limit REAL DEFAULT 5.0,
        alert_threshold REAL DEFAULT 0.8,
        alert_fired INTEGER DEFAULT 0
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        consumer_id TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL,
        completion_tokens INTEGER NOT NULL,
        cost REAL NOT NULL,
        latency_ms INTEGER NOT NULL,
        stream INTEGER NOT NULL,
        FOREIGN KEY (consumer_id) REFERENCES consumers (id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        consumer_id TEXT NOT NULL,
        message TEXT NOT NULL,
        severity TEXT NOT NULL
    )
    """)
    
    # Seed default consumers if table is empty
    cursor.execute("SELECT COUNT(*) FROM consumers")
    if cursor.fetchone()[0] == 0:
        default_consumers = [
            ("equipo-marketing", "Equipo Marketing", 0.0, 5.0, 0.8, 0),
            ("equipo-producto", "Equipo Producto", 0.0, 10.0, 0.8, 0),
            ("default-consumer", "Consumidor por Defecto", 0.0, 2.0, 0.8, 0)
        ]
        cursor.executemany("INSERT INTO consumers VALUES (?, ?, ?, ?, ?, ?)", default_consumers)
        
    conn.commit()
    conn.close()
    logger.info("SQLite database initialized successfully.")

# Initialize SQLite database on module load
init_db()

def get_state():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Retrieve consumers
    cursor.execute("SELECT * FROM consumers")
    consumers = {}
    for r in cursor.fetchall():
        consumers[r["id"]] = {
            "name": r["name"],
            "spent": r["spent"],
            "budget_limit": r["budget_limit"],
            "alert_threshold": r["alert_threshold"],
            "alert_fired": bool(r["alert_fired"])
        }
        
    # Retrieve transactions
    cursor.execute("SELECT * FROM transactions ORDER BY timestamp ASC")
    transactions = []
    for r in cursor.fetchall():
        transactions.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "consumer_id": r["consumer_id"],
            "consumer_name": consumers.get(r["consumer_id"], {}).get("name", r["consumer_id"]),
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
            "consumer_id": r["consumer_id"],
            "consumer_name": consumers.get(r["consumer_id"], {}).get("name", r["consumer_id"]),
            "message": r["message"],
            "severity": r["severity"]
        })
        
    conn.close()
    return {
        "consumers": consumers,
        "transactions": transactions,
        "alerts": alerts
    }

def update_consumer_config(data: dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    for consumer_id, config in data.items():
        # Check if consumer exists, if not create
        cursor.execute("SELECT COUNT(*) FROM consumers WHERE id = ?", (consumer_id,))
        exists = cursor.fetchone()[0] > 0
        if not exists:
            cursor.execute(
                "INSERT INTO consumers (id, name, spent, budget_limit, alert_threshold, alert_fired) VALUES (?, ?, 0.0, 5.0, 0.8, 0)",
                (consumer_id, consumer_id.replace("-", " ").title())
            )
            
        if "budget_limit" in config:
            cursor.execute("UPDATE consumers SET budget_limit = ? WHERE id = ?", (float(config["budget_limit"]), consumer_id))
        if "alert_threshold" in config:
            cursor.execute("UPDATE consumers SET alert_threshold = ? WHERE id = ?", (float(config["alert_threshold"]), consumer_id))
            
        # Reset alert_fired if limit increased above current spend
        cursor.execute("SELECT spent, budget_limit, alert_threshold FROM consumers WHERE id = ?", (consumer_id,))
        row = cursor.fetchone()
        if row:
            spent, limit, threshold = row["spent"], row["budget_limit"], row["alert_threshold"]
            if spent < (limit * threshold):
                cursor.execute("UPDATE consumers SET alert_fired = 0 WHERE id = ?", (consumer_id,))
                
    conn.commit()
    conn.close()
    return get_state()

def reset_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transactions")
    cursor.execute("DELETE FROM alerts")
    cursor.execute("UPDATE consumers SET spent = 0.0, alert_fired = 0")
    conn.commit()
    conn.close()
    return get_state()

def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost = (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000
    return cost

def record_transaction(consumer_id: str, model: str, prompt_tokens: int, completion_tokens: int, cost: float, latency: float, stream: bool = False):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Ensure consumer exists
    cursor.execute("SELECT COUNT(*) FROM consumers WHERE id = ?", (consumer_id,))
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO consumers (id, name, spent, budget_limit, alert_threshold, alert_fired) VALUES (?, ?, 0.0, 5.0, 0.8, 0)",
            (consumer_id, consumer_id.replace("-", " ").title())
        )
        
    # 2. Update consumer spend
    cursor.execute("UPDATE consumers SET spent = spent + ? WHERE id = ?", (cost, consumer_id))
    
    # 3. Read updated info
    cursor.execute("SELECT name, spent, budget_limit, alert_threshold, alert_fired FROM consumers WHERE id = ?", (consumer_id,))
    row = cursor.fetchone()
    name, spent, limit, threshold, alert_fired = row["name"], row["spent"], row["budget_limit"], row["alert_threshold"], row["alert_fired"]
    
    # 4. Insert transaction
    tx_id = f"tx_{int(time.time() * 1000)}"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tx_id, timestamp, consumer_id, model, prompt_tokens, completion_tokens, cost, int(latency * 1000), int(stream))
    )
    
    # 5. Check and fire warnings/alerts
    if spent >= (limit * threshold) and not alert_fired:
        cursor.execute("UPDATE consumers SET alert_fired = 1 WHERE id = ?", (consumer_id,))
        alert_id = f"alert_{int(time.time() * 1000)}"
        message = f"¡Alerta de Gasto! El consumidor '{name}' ha superado el {int(threshold * 100)}% de su límite (${spent:.4f} / ${limit:.2f})"
        cursor.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?)", (alert_id, timestamp, consumer_id, message, "warning"))
        
    if spent >= limit:
        alert_id = f"alert_limit_{int(time.time() * 1000)}"
        message = f"¡LÍMITE EXCEDIDO! El consumidor '{name}' ha agotado su presupuesto (${spent:.4f} / ${limit:.2f})"
        cursor.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?)", (alert_id, timestamp, consumer_id, message, "danger"))
        
    conn.commit()
    conn.close()
