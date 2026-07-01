import time
import logging
import httpx
from flask import Blueprint, request, jsonify, Response

from ..config import PROVIDER_A_URL, PROVIDER_B_URL, PROVIDER_C_URL, GROQ_API_KEY
from ..database import (
    get_db_connection,
    get_state,
    update_consumer_config,
    reset_database,
    record_transaction,
    calculate_cost
)
from ..proxy import (
    resolve_model,
    get_health_status,
    handle_mock_stream,
    handle_mock_non_stream,
    handle_live_stream
)

logger = logging.getLogger("finops_proxy.api")

api_bp = Blueprint("api", __name__)

@api_bp.route("/api/finops/state", methods=["GET"])
def api_get_state():
    return jsonify(get_state())

@api_bp.route("/api/finops/config", methods=["POST"])
def api_update_config():
    data = request.get_json(silent=True) or {}
    new_state = update_consumer_config(data)
    return jsonify({"status": "ok", "state": new_state})

@api_bp.route("/api/finops/reset", methods=["POST"])
def api_reset_db():
    new_state = reset_database()
    return jsonify({"status": "ok", "state": new_state})

@api_bp.route("/api/finops/health", methods=["GET"])
def api_get_health():
    return jsonify(get_health_status())

@api_bp.route("/api/finops/forecast", methods=["GET"])
def api_get_forecast():
    role = request.args.get("role", "todos")
    from ..utils.forecast import get_forecast_data
    return jsonify(get_forecast_data(role))

@api_bp.route("/api/v1/<model_name>", methods=["POST"])
@api_bp.route("/api/v1/<model_name>/chat/completions", methods=["POST"])
def handle_proxy(model_name):
    resolved = resolve_model(model_name)
    if not resolved:
        return jsonify({"detail": f"Model '{model_name}' is not supported. Supported models: llama3.2:3b, mistral:7b, llama-3.1-8b-instant"}), 404

    # 1. User identification (email/username in the header)
    user_id = request.headers.get("x-username") or request.headers.get("x-user") or "default"
    
    # Resolve user to their role in the database and compute total spent of the role
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.rol as role_id, r.nombre as role_name, r.presupuesto_tokens as budget_limit,
               (SELECT COALESCE(SUM(u2.cuota_utilizada), 0) FROM Usuario u2 WHERE u2.rol = r.Id) as spent
        FROM Usuario u 
        JOIN Rol r ON u.rol = r.Id 
        WHERE u.Email = ?
    """, (user_id,))
    row = cursor.fetchone()
    
    if not row:
        # Create user automatically linked to the 'general' role (ID: 3)
        cursor.execute(
            "INSERT OR IGNORE INTO Usuario (Email, nombre, password, rol, cuota_utilizada) VALUES (?, ?, 'default_pass', 3, 0.0)",
            (user_id, user_id.title())
        )
        conn.commit()
        # Query again
        cursor.execute("""
            SELECT u.rol as role_id, r.nombre as role_name, r.presupuesto_tokens as budget_limit,
                   (SELECT COALESCE(SUM(u2.cuota_utilizada), 0) FROM Usuario u2 WHERE u2.rol = r.Id) as spent
            FROM Usuario u 
            JOIN Rol r ON u.rol = r.Id 
            WHERE u.Email = ?
        """, (user_id,))
        row = cursor.fetchone()
        
    role_id = row["role_id"]
    role_name = row["role_name"]
    spent = row["spent"]
    limit = row["budget_limit"]
    conn.close()
    
    # Perform limit verification at the role level
    if spent >= limit:
        msg = f"Presupuesto agotado para el rol '{role_name}' (Usuario: '{user_id}'). Límite: ${limit:.2f}, Gastado: ${spent:.4f}."
        logger.error(msg)
        return jsonify({"detail": msg}), 402

    # 2. Extract request body
    body = request.get_json(silent=True) or {}
    
    # Run KNN classifier if auto-routing is requested
    if resolved == "auto":
        from ..utils.knn_routing import predict_knn_model
        prompt = ""
        for msg in body.get("messages", []):
            prompt += msg.get("content", "")
        prompt_tokens = max(1, round(len(prompt) / 4))
        
        # Predict using KNN classifier
        resolved = predict_knn_model(role_name.lower(), prompt_tokens)
        logger.info(f"KNN Classifier selected model '{resolved}' for role '{role_name}' and {prompt_tokens} prompt tokens.")

    body["model"] = resolved
    
    # Target configurations
    headers = {"Content-Type": "application/json"}
    if resolved == "llama3.2:3b":
        target_url = f"{PROVIDER_A_URL}/chat/completions"
    elif resolved == "mistral:7b":
        target_url = f"{PROVIDER_B_URL}/chat/completions"
    else: # llama-3.1-8b-instant
        target_url = f"{PROVIDER_C_URL}/chat/completions"
        if GROQ_API_KEY:
            headers["Authorization"] = f"Bearer {GROQ_API_KEY}"

    is_stream = body.get("stream", False)
    start_time = time.time()

    # 3. Connection health test to auto-detect if live mode is possible
    is_live = False
    try:
        if resolved == "llama-3.1-8b-instant" and not GROQ_API_KEY:
            raise Exception("Groq key not configured")
            
        ping_url = PROVIDER_A_URL.replace("/v1", "") if resolved == "llama3.2:3b" else (PROVIDER_B_URL.replace("/v1", "") if resolved == "mistral:7b" else PROVIDER_C_URL)
        ping_headers = {"Authorization": f"Bearer {GROQ_API_KEY}"} if (resolved == "llama-3.1-8b-instant" and GROQ_API_KEY) else {}
        
        with httpx.Client(timeout=3.0) as client:
            client.get(ping_url, headers=ping_headers)
        is_live = True
    except Exception as e:
        logger.info(f"Ollama/Groq container offline or API error: {e}. Falling back to simulation.")

    # 4. Fallback Mock mode
    if not is_live:
        if is_stream:
            return Response(handle_mock_stream(resolved, body, user_id, start_time), mimetype="text/event-stream")
        else:
            return jsonify(handle_mock_non_stream(resolved, body, user_id, start_time))

    # 5. Live Mode Proxying
    if is_stream:
        return Response(handle_live_stream(target_url, headers, body, user_id, resolved, start_time), mimetype="text/event-stream")
    else:
        try:
            with httpx.Client(timeout=60.0) as client:
                res = client.post(target_url, headers=headers, json=body)
                if res.status_code != 200:
                    return Response(res.content, status=res.status_code, content_type=res.headers.get("content-type"))
                
                resp_json = res.json()
                usage = resp_json.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                
                if not prompt_tokens or not completion_tokens:
                    char_count = sum(len(msg.get("content", "")) for msg in body.get("messages", []))
                    prompt_tokens = max(1, int(char_count / 4))
                    choices = resp_json.get("choices", [])
                    comp_chars = sum(len(c.get("message", {}).get("content", "")) for c in choices)
                    completion_tokens = max(1, int(comp_chars / 4))
                
                latency = time.time() - start_time
                cost = calculate_cost(resolved, prompt_tokens, completion_tokens)
                record_transaction(user_id, resolved, prompt_tokens, completion_tokens, cost, latency, stream=False)
                return jsonify(resp_json)
        except Exception as e:
            logger.error(f"Error during live non-stream proxy: {e}")
            return jsonify({"detail": str(e)}), 500
