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
    
    # Pre-extract prompt for logging and routing
    prompt = ""
    for msg in body.get("messages", []):
        prompt += msg.get("content", "")
    prompt_tokens = max(1, round(len(prompt) / 4))
    
    is_auto_routed = (model_name.lower().strip() == "auto")
    
    # Run KNN classifier if auto-routing is requested
    if resolved == "auto":
        from ..utils.knn_routing import predict_knn_model
        import sys
        import os
        workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        if workspace_root not in sys.path:
            sys.path.insert(0, workspace_root)
        from testing.analyzer_simple import analyze_query
        
        query_scores = analyze_query(prompt)

        # Predict using KNN classifier, passing all dimensions including tamano_respuesta
        resolved = predict_knn_model(
            role_name.lower(), 
            prompt_tokens, 
            query_scores.get('concretitud', 0.0), 
            query_scores.get('especificacion', 0.0), 
            query_scores.get('criticidad', 0.0),
            query_scores.get('tamano_respuesta', 0.0)
        )
        logger.info(f"KNN Classifier selected model '{resolved}' for role '{role_name}', {prompt_tokens} prompt tokens and {query_scores} query scores.")

    body["model"] = resolved
    body["is_auto_routed"] = is_auto_routed
    body["prompt_text"] = prompt
    
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
            clean_body = {k: v for k, v in body.items() if k not in ["is_auto_routed", "prompt_text"]}
            with httpx.Client(timeout=60.0) as client:
                res = client.post(target_url, headers=headers, json=clean_body)
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
                
                import json
                query_data = {
                    "prompt": prompt[:200] + ("..." if len(prompt) > 200 else ""),
                    "routing": "Auto (KNN)" if is_auto_routed else "Directo"
                }
                query_text = json.dumps(query_data)
                record_transaction(user_id, resolved, prompt_tokens, completion_tokens, cost, latency, stream=False, query_text=query_text)
                return jsonify(resp_json)
        except Exception as e:
            logger.error(f"Error during live non-stream proxy: {e}")
            return jsonify({"detail": str(e)}), 500

@api_bp.route("/api/finops/models-pricing", methods=["GET"])
def api_get_models_pricing():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT Nombre, cpt_in, cpt_out FROM Modelo")
    rows = cursor.fetchall()
    conn.close()
    
    pricing = {}
    for r in rows:
        pricing[r["Nombre"]] = {
            "input": float(r["cpt_in"]) * 1_000_000,
            "output": float(r["cpt_out"]) * 1_000_000
        }
    return jsonify(pricing)

@api_bp.route("/api/finops/reports", methods=["GET"])
def api_get_reports():
    import datetime
    import json
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch benchmark Mistral rate per token from database
    cursor.execute("SELECT cpt_in, cpt_out FROM Modelo WHERE Nombre = 'mistral:7b'")
    mistral_row = cursor.fetchone()
    mistral_cpt_in = float(mistral_row["cpt_in"]) if mistral_row else 0.00000024
    mistral_cpt_out = float(mistral_row["cpt_out"]) if mistral_row else 0.00000024
    
    # 1. Total Metrics
    cursor.execute("""
        SELECT COUNT(*) as total_requests,
               COALESCE(SUM(q.Num_tokens_in), 0) as total_prompt_tokens,
               COALESCE(SUM(q.Num_tokens_out), 0) as total_completion_tokens,
               COALESCE(SUM(q.Num_tokens_in * m.cpt_in + q.Num_tokens_out * m.cpt_out), 0.0) as total_cost
        FROM Query q
        JOIN Modelo m ON q.Modelo = m.Nombre
    """)
    totals = dict(cursor.fetchone())
    
    # 2. Consumer Stats (grouped by user)
    cursor.execute("""
        SELECT u.Email as user_id, u.nombre as user_name, r.nombre as role_name,
               COUNT(q.Usuario) as count,
               COALESCE(SUM(q.Num_tokens_in), 0) as prompt,
               COALESCE(SUM(q.Num_tokens_out), 0) as completion,
               COALESCE(SUM(q.Num_tokens_in * m.cpt_in + q.Num_tokens_out * m.cpt_out), 0.0) as cost
        FROM Query q
        JOIN Usuario u ON q.Usuario = u.Email
        JOIN Rol r ON u.rol = r.Id
        JOIN Modelo m ON q.Modelo = m.Nombre
        GROUP BY u.Email
    """)
    consumer_rows = cursor.fetchall()
    consumer_stats = {}
    for r in consumer_rows:
        consumer_stats[r["user_id"]] = {
            "name": f"{r['user_name']} ({r['role_name'].title()})",
            "count": r["count"],
            "prompt": r["prompt"],
            "completion": r["completion"],
            "cost": float(r["cost"]),
            "avg_cost": float(r["cost"]) / r["count"] if r["count"] > 0 else 0.0
        }
    
    # Ensure all DB users are present even with 0 counts
    cursor.execute("""
        SELECT u.Email as email, u.nombre as name, r.nombre as role_name
        FROM Usuario u
        JOIN Rol r ON u.rol = r.Id
    """)
    for u in cursor.fetchall():
        if u["email"] not in consumer_stats:
            consumer_stats[u["email"]] = {
                "name": f"{u['name']} ({u['role_name'].title()})",
                "count": 0,
                "prompt": 0,
                "completion": 0,
                "cost": 0.0,
                "avg_cost": 0.0
            }
            
    # 3. Model Stats
    cursor.execute("""
        SELECT m.Nombre as model,
               COUNT(q.Modelo) as count,
               COALESCE(SUM(q.Num_tokens_in), 0) as prompt,
               COALESCE(SUM(q.Num_tokens_out), 0) as completion,
               COALESCE(SUM(q.Num_tokens_in * m.cpt_in + q.Num_tokens_out * m.cpt_out), 0.0) as cost
        FROM Modelo m
        LEFT JOIN Query q ON q.Modelo = m.Nombre
        GROUP BY m.Nombre
    """)
    model_rows = cursor.fetchall()
    model_stats = {}
    for r in model_rows:
        model_stats[r["model"]] = {
            "count": r["count"],
            "prompt": r["prompt"],
            "completion": r["completion"],
            "cost": float(r["cost"])
        }
        
    # 4. Savings Calculations
    cursor.execute("""
        SELECT q.Fecha as timestamp, q.Consulta as query_text, q.Modelo as model,
               q.Num_tokens_in as prompt_tokens, q.Num_tokens_out as completion_tokens,
               (q.Num_tokens_in * m.cpt_in + q.Num_tokens_out * m.cpt_out) as cost
        FROM Query q
        JOIN Modelo m ON q.Modelo = m.Nombre
        ORDER BY q.Fecha ASC
    """)
    queries = cursor.fetchall()
    conn.close()
    
    total_routed_cost = 0.0
    total_mistral_cost = 0.0
    labels = []
    cumulative_routed = []
    cumulative_mistral = []
    
    for q in queries:
        prompt_tokens = q["prompt_tokens"]
        completion_tokens = q["completion_tokens"]
        mistral_cost = (prompt_tokens * mistral_cpt_in) + (completion_tokens * mistral_cpt_out)
        routed_cost = float(q["cost"])
        
        total_routed_cost += routed_cost
        total_mistral_cost += mistral_cost
        
        try:
            d = datetime.datetime.strptime(q["timestamp"], "%Y-%m-%d %H:%M:%S")
            time_str = d.strftime("%H:%M:%S")
        except Exception:
            time_str = q["timestamp"]
            
        labels.append(time_str)
        cumulative_routed.append(total_routed_cost)
        cumulative_mistral.append(total_mistral_cost)
        
    total_saved = total_mistral_cost - total_routed_cost
    pct_saved = (total_saved / total_mistral_cost * 100) if total_mistral_cost > 0 else 0.0
    
    # 5. Last 5 Activations
    last_5_activations = []
    for q in reversed(queries):
        if len(last_5_activations) >= 5:
            break
        prompt_tokens = q["prompt_tokens"]
        completion_tokens = q["completion_tokens"]
        mistral_cost = (prompt_tokens * mistral_cpt_in) + (completion_tokens * mistral_cpt_out)
        routed_cost = float(q["cost"])
        saved = mistral_cost - routed_cost
        
        prompt_text = "API Request"
        routing_rule = "Directo"
        try:
            parsed = json.loads(q["query_text"])
            prompt_text = parsed.get("prompt", q["query_text"])
            routing_rule = parsed.get("routing", "Directo")
        except Exception:
            if q["query_text"]:
                prompt_text = q["query_text"]
                
        last_5_activations.append({
            "prompt_text": prompt_text,
            "routing_rule": routing_rule,
            "model": q["model"],
            "cost": routed_cost,
            "saved": saved
        })
        
    return jsonify({
        "totals": totals,
        "consumer_stats": consumer_stats,
        "model_stats": model_stats,
        "savings": {
            "total_routed_cost": total_routed_cost,
            "total_mistral_cost": total_mistral_cost,
            "total_saved": total_saved,
            "pct_saved": pct_saved,
            "last_5_activations": last_5_activations,
            "chart": {
                "labels": labels,
                "cumulative_routed": cumulative_routed,
                "cumulative_mistral": cumulative_mistral
            }
        }
    })


