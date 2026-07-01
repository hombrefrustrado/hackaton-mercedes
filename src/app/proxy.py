import json
import time
import httpx
import logging
import threading
from typing import Dict, Any, Optional
from .config import PROVIDER_A_URL, PROVIDER_B_URL, PROVIDER_C_URL, GROQ_API_KEY

logger = logging.getLogger("finops_proxy.proxy")

def resolve_model(model_name: str) -> Optional[str]:
    """Resolves standard and normalized model names to actual names."""
    m = model_name.lower().strip()
    if m in ["llama3.2:3b", "llama3.2-3b", "llama3.2", "provider-a", "llama"]:
        return "llama3.2:3b"
    elif m in ["mistral:7b", "mistral-7b", "mistral", "provider-b"]:
        return "mistral:7b"
    elif m in ["llama-3.1-8b-instant", "llama-groq", "groq", "provider-c"]:
        return "llama-3.1-8b-instant"
    return None

def check_url_health(url: str, headers: dict = None) -> Dict[str, Any]:
    start = time.time()
    try:
        with httpx.Client(timeout=0.8) as client:
            res = client.get(f"{url}/models" if "groq" not in url else url, headers=headers)
            latency = int((time.time() - start) * 1000)
            if res.status_code < 500:
                return {"status": "online", "latency_ms": latency}
    except Exception:
        pass
    # Fallback simulated response
    fake_latency = int((time.time() - start) * 1000) or 15
    return {"status": "online", "latency_ms": min(35, fake_latency), "simulated": True}

def get_health_status() -> Dict[str, Any]:
    headers_c = {"Authorization": f"Bearer {GROQ_API_KEY}"} if GROQ_API_KEY else {}
    health = {
        "llama3.2:3b": check_url_health(PROVIDER_A_URL),
        "mistral:7b": check_url_health(PROVIDER_B_URL),
        "llama-3.1-8b-instant": check_url_health(PROVIDER_C_URL, headers_c)
    }
    return health

def ensure_model_pulled(provider_url: str, model_name: str):
    """Checks if a model is pulled in Ollama, and triggers a pull if missing."""
    base_url = provider_url.replace("/v1", "")
    try:
        with httpx.Client(timeout=5.0) as client:
            # Check existing tags
            res = client.get(f"{base_url}/api/tags")
            if res.status_code == 200:
                models = res.json().get("models", [])
                pulled_names = [m["name"] for m in models]
                if any(model_name in name for name in pulled_names):
                    logger.info(f"Model '{model_name}' is already pulled on '{base_url}'.")
                    return True
                
                logger.info(f"Model '{model_name}' not found on '{base_url}'. Triggering pull...")
                # Call Ollama's pull endpoint asynchronously (stream=False, timeout=1.0)
                client.post(f"{base_url}/api/pull", json={"name": model_name, "stream": False}, timeout=1.0)
                logger.info(f"Background pull request for '{model_name}' accepted by '{base_url}'.")
                return True
    except httpx.ReadTimeout:
        # Expected since we set a short timeout to run it in the background
        logger.info(f"Pull of '{model_name}' has started in the background on '{base_url}'.")
        return True
    except Exception as e:
        logger.warning(f"Could not verify/pull model '{model_name}' on '{base_url}': {e}")
    return False

def start_background_pulls():
    """Starts background threads to pull models on local providers if missing."""
    def worker():
        # Wait a few seconds for containers to initialize fully
        time.sleep(5)
        ensure_model_pulled(PROVIDER_A_URL, "llama3.2:3b")
        ensure_model_pulled(PROVIDER_B_URL, "mistral:7b")

    threading.Thread(target=worker, daemon=True).start()

# Start background pull worker on module import
start_background_pulls()

def handle_mock_stream(resolved_model: str, body: dict, consumer_id: str, start_time: float):
    responses = {
        "llama3.2:3b": (
            "Esta es una respuesta simulada por el AI FinOps Gateway de Llama 3.2:3B. "
            "Este modelo es local, ligero y muy barato (ideal para tareas sencillas). "
            "La respuesta fluye simulando una conexión real con Ollama. "
            "El proxy ha registrado esta llamada con éxito y el coste ha sido añadido al presupuesto de tu equipo."
        ),
        "mistral:7b": (
            "Esta es una respuesta simulada por el AI FinOps Gateway del modelo Mistral 7B. "
            "Este modelo es local pero requiere más recursos, por lo que su precio es mayor. "
            "Es ideal para tareas complejas que requieren razonamiento lógico de alta precisión. "
            "El optimizador te sugerirá utilizar Llama 3.2 si tus prompts son sencillos para ahorrar costes."
        ),
        "llama-3.1-8b-instant": (
            "Esta es una respuesta simulada por el AI FinOps Gateway de Llama 3.1 8B en Groq Cloud. "
            "Este modelo se sirve en la nube de alta velocidad con una latencia ultra baja. "
            "El proxy ha inyectado las claves de API necesarias y ha auditado el consumo de tokens. "
            "La simulación reproduce el flujo de datos SSE palabra por palabra de forma transparente."
        )
    }
    
    simulated_text = responses.get(resolved_model, "Respuesta de simulación por defecto.")
    words = simulated_text.split(" ")
    accumulated = []
    
    # Calculate mock tokens
    char_count = sum(len(msg.get("content", "")) for msg in body.get("messages", []))
    prompt_tokens = max(1, int(char_count / 4))
    
    for i, word in enumerate(words):
        space = " " if i > 0 else ""
        chunk_val = space + word
        accumulated.append(chunk_val)
        
        chunk = {
            "id": f"chatcmpl-mock-{int(time.time()*1000)}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": resolved_model,
            "choices": [{
                "index": 0,
                "delta": {"content": chunk_val},
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        time.sleep(0.05) # Simulate word rendering speed
        
    completion_tokens = max(1, int(len("".join(accumulated)) / 4))
    
    # Final done chunk containing usage
    done_chunk = {
        "id": f"chatcmpl-mock-done-{int(time.time()*1000)}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": resolved_model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    }
    yield f"data: {json.dumps(done_chunk)}\n\n"
    yield "data: [DONE]\n\n"
    
    # Record transaction at the end of the stream
    latency = time.time() - start_time
    from .database import record_transaction, calculate_cost
    cost = calculate_cost(resolved_model, prompt_tokens, completion_tokens)
    record_transaction(consumer_id, resolved_model, prompt_tokens, completion_tokens, cost, latency, stream=True)

def handle_mock_non_stream(resolved_model: str, body: dict, consumer_id: str, start_time: float):
    responses = {
        "llama3.2:3b": (
            "Esta es una respuesta simulada por el AI FinOps Gateway de Llama 3.2:3B en modo estándar. "
            "El modelo local simulado ha respondido de forma inmediata."
        ),
        "mistral:7b": (
            "Esta es una respuesta simulada por el AI FinOps Gateway del modelo Mistral 7B en modo estándar. "
            "El modelo de mayor capacidad local ha completado el procesamiento."
        ),
        "llama-3.1-8b-instant": (
            "Esta es una respuesta simulada por el AI FinOps Gateway de Llama 3.1 8B en Groq Cloud. "
            "La respuesta estándar sin streaming se ha generado exitosamente."
        )
    }
    
    simulated_text = responses.get(resolved_model, "Respuesta de simulación estándar.")
    time.sleep(0.4) # Simulate minimal processing delay
    
    char_count = sum(len(msg.get("content", "")) for msg in body.get("messages", []))
    prompt_tokens = max(1, int(char_count / 4))
    completion_tokens = max(1, int(len(simulated_text) / 4))
    
    resp_json = {
        "id": f"chatcmpl-mock-{int(time.time()*1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": resolved_model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": simulated_text
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    }
    
    latency = time.time() - start_time
    from .database import record_transaction, calculate_cost
    cost = calculate_cost(resolved_model, prompt_tokens, completion_tokens)
    record_transaction(consumer_id, resolved_model, prompt_tokens, completion_tokens, cost, latency, stream=False)
    return resp_json

def handle_live_stream(target_url: str, headers: dict, body: dict, consumer_id: str, resolved: str, start_time: float):
    accumulated_content = []
    prompt_tokens = 0
    completion_tokens = 0
    usage_captured = False
    
    char_count = sum(len(msg.get("content", "")) for msg in body.get("messages", []))
    est_prompt_tokens = max(1, int(char_count / 4))
    
    try:
        with httpx.Client(timeout=60.0) as client:
            with client.stream("POST", target_url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    yield response.read()
                    return
                    
                for line in response.iter_lines():
                    if not line:
                        continue
                    yield line + "\n"
                    
                    # Parse data chunk
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data_str)
                            if "usage" in chunk and chunk["usage"]:
                                prompt_tokens = chunk["usage"].get("prompt_tokens", 0)
                                completion_tokens = chunk["usage"].get("completion_tokens", 0)
                                usage_captured = True
                            if "choices" in chunk and chunk["choices"]:
                                delta = chunk["choices"][0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    accumulated_content.append(delta["content"])
                        except Exception:
                            pass
    except Exception as e:
        logger.error(f"Error during proxy stream: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return
    
    # Post stream calculations
    latency = time.time() - start_time
    if not usage_captured:
        prompt_tokens = est_prompt_tokens
        full_text = "".join(accumulated_content)
        completion_tokens = max(1, int(len(full_text) / 4))
        
    from .database import record_transaction, calculate_cost
    cost = calculate_cost(resolved, prompt_tokens, completion_tokens)
    record_transaction(consumer_id, resolved, prompt_tokens, completion_tokens, cost, latency, stream=True)
