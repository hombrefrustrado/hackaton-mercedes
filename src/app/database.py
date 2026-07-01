import json
import os
import time
import logging
from .config import DB_FILE, PRICING

logger = logging.getLogger("finops_proxy.database")

DEFAULT_STATE = {
    "consumers": {
        "equipo-marketing": {
            "name": "Equipo Marketing",
            "spent": 0.0,
            "budget_limit": 5.0,
            "alert_threshold": 0.8,
            "alert_fired": False
        },
        "equipo-producto": {
            "name": "Equipo Producto",
            "spent": 0.0,
            "budget_limit": 10.0,
            "alert_threshold": 0.8,
            "alert_fired": False
        },
        "default-consumer": {
            "name": "Consumidor por Defecto",
            "spent": 0.0,
            "budget_limit": 2.0,
            "alert_threshold": 0.8,
            "alert_fired": False
        }
    },
    "transactions": [],
    "alerts": []
}

state = DEFAULT_STATE.copy()

def load_db():
    global state
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                loaded = json.load(f)
                if "consumers" in loaded:
                    for k, v in loaded["consumers"].items():
                        if k in state["consumers"]:
                            state["consumers"][k].update(v)
                        else:
                            state["consumers"][k] = v
                state["transactions"] = loaded.get("transactions", [])
                state["alerts"] = loaded.get("alerts", [])
                logger.info("Database loaded from file.")
        except Exception as e:
            logger.error(f"Error loading database: {e}")

def save_db():
    try:
        with open(DB_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving database: {e}")

# Initial load
load_db()

def get_state():
    return state

def update_consumer_config(data: dict):
    global state
    for consumer_id, config in data.items():
        if consumer_id in state["consumers"]:
            if "budget_limit" in config:
                state["consumers"][consumer_id]["budget_limit"] = float(config["budget_limit"])
            if "alert_threshold" in config:
                state["consumers"][consumer_id]["alert_threshold"] = float(config["alert_threshold"])
            
            # Reset alert_fired if limit increased above current spend
            spent = state["consumers"][consumer_id]["spent"]
            limit = state["consumers"][consumer_id]["budget_limit"]
            threshold = state["consumers"][consumer_id]["alert_threshold"]
            if spent < (limit * threshold):
                state["consumers"][consumer_id]["alert_fired"] = False
    save_db()
    return state

def reset_database():
    global state
    state["transactions"] = []
    state["alerts"] = []
    for k in state["consumers"]:
        state["consumers"][k]["spent"] = 0.0
        state["consumers"][k]["alert_fired"] = False
    save_db()
    return state

def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost = (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000
    return cost

def record_transaction(consumer_id: str, model: str, prompt_tokens: int, completion_tokens: int, cost: float, latency: float, stream: bool = False):
    global state
    if consumer_id not in state["consumers"]:
        state["consumers"][consumer_id] = {
            "name": consumer_id.replace("-", " ").title(),
            "spent": 0.0,
            "budget_limit": 5.0,
            "alert_threshold": 0.8,
            "alert_fired": False
        }
    
    consumer = state["consumers"][consumer_id]
    consumer["spent"] += cost
    spent = consumer["spent"]
    limit = consumer["budget_limit"]
    threshold = consumer["alert_threshold"]

    # Log transaction
    tx = {
        "id": f"tx_{int(time.time() * 1000)}",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "consumer_id": consumer_id,
        "consumer_name": consumer["name"],
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "latency_ms": int(latency * 1000),
        "stream": stream
    }
    state["transactions"].append(tx)
    
    # Check alert threshold
    if spent >= (limit * threshold) and not consumer.get("alert_fired", False):
        consumer["alert_fired"] = True
        alert = {
            "id": f"alert_{int(time.time() * 1000)}",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "consumer_id": consumer_id,
            "consumer_name": consumer["name"],
            "message": f"¡Alerta de Gasto! El consumidor '{consumer['name']}' ha superado el {int(threshold * 100)}% de su límite (${spent:.4f} / ${limit:.2f})",
            "severity": "warning"
        }
        state["alerts"].append(alert)
        logger.warning(f"Alert fired for consumer {consumer_id}: {alert['message']}")

    # Limit hit alert
    if spent >= limit:
        alert = {
            "id": f"alert_limit_{int(time.time() * 1000)}",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "consumer_id": consumer_id,
            "consumer_name": consumer["name"],
            "message": f"¡LÍMITE EXCEDIDO! El consumidor '{consumer['name']}' ha agotado su presupuesto (${spent:.4f} / ${limit:.2f})",
            "severity": "danger"
        }
        state["alerts"].append(alert)
        logger.error(f"Budget limit exceeded for consumer {consumer_id}")

    save_db()
