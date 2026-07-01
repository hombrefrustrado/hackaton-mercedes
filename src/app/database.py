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
    
    # 1. Crear tabla Rol
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Rol (
        Id INTEGER PRIMARY KEY,
        nombre TEXT NOT NULL,
        presupuesto_tokens NUMERIC
    )
    """)

    # 2. Crear tabla Modelo
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Modelo (
        Nombre TEXT PRIMARY KEY,
        cpt_in NUMERIC,
        cpt_out NUMERIC
    )
    """)

    # 3. Crear tabla Usuario (Clave primaria: Email)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Usuario (
        Email TEXT PRIMARY KEY,
        nombre TEXT NOT NULL,
        password TEXT NOT NULL,
        rol INTEGER,
        cuota_utilizada NUMERIC DEFAULT 0,
        FOREIGN KEY (rol) REFERENCES Rol(Id)
    )
    """)

    # 4. Crear tabla Query (Usuario actúa como Foreign Key hacia Usuario.Email)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Query (
        Usuario TEXT,
        Fecha TIMESTAMP,
        Consulta VARCHAR,
        Modelo VARCHAR,
        Num_tokens_out NUMERIC,
        Num_tokens_in NUMERIC,
        PRIMARY KEY (Usuario, Fecha),
        FOREIGN KEY (Usuario) REFERENCES Usuario(Email),
        FOREIGN KEY (Modelo) REFERENCES Modelo(Nombre)
    )
    """)

    # 5. Crear el Trigger corrigiendo la asociación por Email
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_actualizar_cuota_usuario
    BEFORE INSERT ON Query
    FOR EACH ROW
    BEGIN
        UPDATE Usuario
        SET cuota_utilizada = cuota_utilizada + (
            (NEW.Num_tokens_in * (SELECT cpt_in FROM Modelo WHERE Nombre = NEW.Modelo)) +
            (NEW.Num_tokens_out * (SELECT cpt_out FROM Modelo WHERE Nombre = NEW.Modelo))
        )
        WHERE Email = NEW.Usuario;
    END;
    """)

    print("¡Tablas y trigger corregidos y creados exitosamente!")
    
    # Seed de Modelos desde el diccionario PRICING si está vacío
    cursor.execute("SELECT COUNT(*) FROM Modelo")
    if cursor.fetchone()[0] == 0:
        for model_name, rates in PRICING.items():
            # Convertimos el precio por millón a coste unitario por token para el Trigger
            cpt_in = rates.get("input", 0.0) / 1_000_000
            cpt_out = rates.get("output", 0.0) / 1_000_000
            cursor.execute("INSERT INTO Modelo VALUES (?, ?, ?)", (model_name, cpt_in, cpt_out))
    
    # Seed de Roles por defecto si está vacío
    cursor.execute("SELECT COUNT(*) FROM Rol")
    if cursor.fetchone()[0] == 0:
        default_roles = [
            (1, "marketing", 5.0),   # Presupuesto asignado (ej. equivalente a $5.0)
            (2, "desarrollo", 10.0),   # Presupuesto asignado (ej. equivalente a $10.0)
            (3, "RRHH", 2.0)      # Presupuesto asignado (ej. equivalente a $2.0)
        ]
        cursor.executemany("INSERT INTO Rol VALUES (?, ?, ?)", default_roles)
        
    # Seed de Usuarios por defecto vinculados a sus roles si está vacío
    cursor.execute("SELECT COUNT(*) FROM Usuario")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ("ana", "Ana", "pbkdf2:sha256...", 1, 0.0),
            ("carlos", "Carlos", "pbkdf2:sha256...", 2, 0.0),
            ("paco", "Paco", "pbkdf2:sha256...", 3, 0.0)
        ]
        cursor.executemany("INSERT INTO Usuario VALUES (?, ?, ?, ?, ?)", default_users)
        
    conn.commit()
    conn.close()
    logger.info("SQLite database initialized with clean Relational Schema.")

# Inicializar Base de datos al cargar el módulo
init_db()

def get_state():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Mapear Consumidores (Roles) calculando el gasto acumulado de sus usuarios
    cursor.execute("""
        SELECT r.Id, r.nombre, r.presupuesto_tokens, COALESCE(SUM(u.cuota_utilizada), 0) as spent
        FROM Rol r
        LEFT JOIN Usuario u ON u.rol = r.Id
        GROUP BY r.Id
    """)
    consumers = {}
    roles_data = cursor.fetchall()
    
    for r in roles_data:
        role_key = r["nombre"].lower()
        spent = r["spent"]
        limit = r["presupuesto_tokens"]
        
        consumers[role_key] = {
            "name": r["nombre"].title(),
            "spent": spent,
            "budget_limit": limit,
            "alert_threshold": 0.8, # Umbral por defecto al 80%
            "alert_fired": spent >= (limit * 0.8) if limit > 0 else False
        }
        
    # 2. Recuperar el historial de transacciones desde la tabla Query
    cursor.execute("""
        SELECT q.rowid as id, q.Fecha as timestamp, q.Usuario as user_id, 
               u.nombre as user_name, r.nombre as role_name, q.Modelo as model,
               q.Num_tokens_in as prompt_tokens, q.Num_tokens_out as completion_tokens,
               (q.Num_tokens_in * m.cpt_in + q.Num_tokens_out * m.cpt_out) as cost
        FROM Query q
        JOIN Usuario u ON q.Usuario = u.Email
        JOIN Rol r ON u.rol = r.Id
        JOIN Modelo m ON q.Modelo = m.Nombre
        ORDER BY q.Fecha ASC
    """)
    transactions = []
    for r in cursor.fetchall():
        transactions.append({
            "id": f"tx_{r['id']}",
            "timestamp": r["timestamp"],
            "consumer_id": r["user_id"],
            "consumer_name": f"{r['user_name']} ({r['role_name'].title()})",
            "model": r["model"],
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "cost": r["cost"],
            "latency_ms": 0,       # No guardado en el esquema actual (mockeado para UI)
            "stream": False        # No guardado en el esquema actual (mockeado para UI)
        })
        
    # 3. Generar Alertas Dinámicas basadas en el presupuesto consumido actual
    alerts = []
    for r in roles_data:
        role_key = r["nombre"].lower()
        spent = r["spent"]
        limit = r["presupuesto_tokens"]
        
        if limit > 0:
            if spent >= limit:
                alerts.append({
                    "id": f"alert_limit_{role_key}_{int(time.time())}",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "consumer_id": role_key,
                    "consumer_name": r["nombre"].title(),
                    "message": f"¡LÍMITE EXCEDIDO! El rol '{r['nombre']}' ha agotado su presupuesto (${spent:.4f} / ${limit:.2f})",
                    "severity": "danger"
                })
            elif spent >= (limit * 0.8):
                alerts.append({
                    "id": f"alert_warn_{role_key}_{int(time.time())}",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "consumer_id": role_key,
                    "consumer_name": r["nombre"].title(),
                    "message": f"¡Alerta de Gasto! El rol '{r['nombre']}' ha superado el 80% de su límite (${spent:.4f} / ${limit:.2f})",
                    "severity": "warning"
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
    for role_id, config in data.items():
        if "budget_limit" in config:
            cursor.execute("UPDATE Rol SET presupuesto_tokens = ? WHERE LOWER(nombre) = LOWER(?)", (float(config["budget_limit"]), role_id))
            
    conn.commit()
    conn.close()
    return get_state()

def reset_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM Query")
    cursor.execute("UPDATE Usuario SET cuota_utilizada = 0.0")
    conn.commit()
    conn.close()
    return get_state()

def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    # Intenta obtener el coste dinámicamente desde la tabla Modelo
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT cpt_in, cpt_out FROM Modelo WHERE Nombre = ?", (model,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return (prompt_tokens * row["cpt_in"]) + (completion_tokens * row["cpt_out"])
    except Exception:
        pass
        
    # Fallback al diccionario estático si la DB no está disponible
    rates = PRICING.get(model, {"input": 0.0, "output": 0.0})
    return (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000

def record_transaction(user_id: str, model: str, prompt_tokens: int, completion_tokens: int, cost: float, latency: float, stream: bool = False):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Asegurar que el usuario existe en la tabla Usuario; si no, lo vinculamos al rol 'general' (ID: 3)
    cursor.execute("SELECT rol FROM Usuario WHERE Email = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            "INSERT OR IGNORE INTO Usuario (Email, nombre, password, rol, cuota_utilizada) VALUES (?, ?, 'default_pass', 3, 0.0)", 
            (user_id, user_id.title())
        )
        
    # 2. Insertar la transacción en la tabla Query
    # ¡Ojo! El trigger 'trg_actualizar_cuota_usuario' se encargará automáticamente de actualizar la cuota del usuario.
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO Query (Usuario, Fecha, Consulta, Modelo, Num_tokens_out, Num_tokens_in) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, timestamp, "API Proxy Request", model, completion_tokens, prompt_tokens)
    )
        
    conn.commit()
    conn.close()