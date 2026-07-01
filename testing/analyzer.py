"""
analyzer.py — Analizador de complejidad e intención de queries.

Evalúa un prompt de texto en 4 dimensiones y devuelve un score de 0 a 10 para cada una:

  - concretitud:    Qué tan específica e instruccional es la pregunta (palabras como "exactamente", "paso a paso")
  - especificacion: Qué tan técnica/detallada es en términos de dominio o código
  - criticidad:     Qué tan urgente o de alto impacto parece (palabras como "urgente", "error", "producción")
  - tamano_respuesta: Qué tan larga se espera que sea la respuesta (basado en indicadores de tamaño en el texto)

Estos scores pueden usarse para enrutar a un modelo más barato o más potente.
"""

import re

# ---------------------------------------------------------------------------
# Word lists per dimension
# ---------------------------------------------------------------------------

CONCRETENESS_KEYWORDS = [
    "exactamente", "paso a paso", "paso-a-paso", "detallado", "detallada",
    "detalle", "lista", "listado", "enumera", "explica", "describir",
    "describe", "instrucciones", "guía", "guia", "procedimiento", "proceso",
    "cómo", "como", "cuánto", "cuanto", "cuántos", "cuantos",
    "muéstrame", "muéstrame", "dime", "indica", "indicame", "qué es", "qué son",
    "define", "definicion", "definición"
]

SPECIFICATION_KEYWORDS = [
    # Technical / code indicators
    "código", "codigo", "código python", "código sql", "función", "funcion",
    "script", "api", "endpoint", "json", "yaml", "xml", "csv", "sql",
    "consulta", "query", "base de datos", "database", "servidor", "server",
    "docker", "kubernetes", "deploy", "deployment", "arquitectura", "microservicio",
    "pipeline", "algoritmo", "modelo", "machine learning", "ml", "ia", "llm",
    "token", "embedding", "prompt", "regex", "http", "rest", "graphql",
    "autenticacion", "autenticación", "oauth", "jwt", "ssl", "tls", "cifrado",
    "clase", "objeto", "instancia", "interface", "middleware",
]

CRITICALITY_KEYWORDS = [
    "urgente", "urgencia", "inmediatamente", "inmediato", "crítico", "critico",
    "crítica", "critica", "producción", "produccion", "error", "bug", "fallo",
    "caída", "caida", "bloqueado", "bloqueante", "seguridad", "vulnerabilidad",
    "brecha", "filtración", "filtracion", "legal", "compliance", "normativa",
    "gdpr", "regulación", "regulacion", "auditoría", "auditoria", "deadline",
    "fecha límite", "impacto", "pérdida", "perdida", "riesgo", "alerta",
    "emergencia", "incidente", "interrupción", "interrupcion", "downtime",
]

LONG_RESPONSE_KEYWORDS = [
    "completo", "completa", "detallado", "detallada", "exhaustivo", "exhaustiva",
    "informe", "reporte", "ensayo", "redacta", "escribe", "elabora", "desarrolla",
    "guion", "guión", "script", "plan", "estrategia", "análisis", "analisis",
    "comparativa", "comparación", "comparacion", "propuesta", "presentación",
    "presentacion", "documento", "memoria", "nota de prensa", "artículo", "articulo",
    "tutorial", "manual", "documentación", "documentacion", "descripción", "descripcion",
    "8 minutos", "1000 palabras", "500 palabras", "1000 tokens", "largo", "extensa", "extenso",
]

SHORT_RESPONSE_KEYWORDS = [
    "resumen", "resumir", "brevemente", "breve", "corto", "corta", "sencillo", "sencilla",
    "simple", "rápido", "rapido", "en una línea", "en una frase", "en pocas palabras",
    "tldr", "tl;dr", "one-liner", "ejemplo simple",
]


def _keyword_score(text: str, keywords: list[str], max_score: float = 10.0) -> float:
    """
    Returns a score based on how many of the given keywords appear in the text.
    The score saturates at max_score and is normalized to a 0-10 scale.
    """
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw in text_lower)
    # Scoring: each hit is worth ~2.5 points, capped at max_score
    raw = hits * 2.5
    return round(min(raw, max_score), 2)


def _length_score(text: str) -> float:
    """
    Returns a score (0-10) based on word count.
    Short queries (< 10 words) → 0-2, medium → 3-6, long → 7-10.
    """
    words = len(text.split())
    if words < 10:
        return round(min(words / 10 * 2.0, 2.0), 2)
    elif words < 30:
        return round(2.0 + (words - 10) / 20 * 4.0, 2)
    elif words < 80:
        return round(6.0 + (words - 30) / 50 * 3.0, 2)
    else:
        return 10.0


def analyze_query(prompt: str) -> dict:
    """
    Analyzes a prompt and returns a complexity profile with 4 scores (0-10):

      - concretitud:      How instructional and concrete the query is
      - especificacion:   How technical / domain-specific the query is
      - criticidad:       How urgent or high-impact the query seems
      - tamano_respuesta: Expected length of the response (higher = longer)

    Args:
        prompt: The raw user-facing text to analyze.

    Returns:
        A dict with the 4 float scores.
    """
    if not prompt or not prompt.strip():
        return {
            "concretitud": 0.0,
            "especificacion": 0.0,
            "criticidad": 0.0,
            "tamano_respuesta": 0.0,
        }

    # --- Concretitud ---
    concreteness = _keyword_score(prompt, CONCRETENESS_KEYWORDS)

    # --- Especificación: keyword hits + a bonus for longer prompts ---
    spec_keyword = _keyword_score(prompt, SPECIFICATION_KEYWORDS)
    spec_length_bonus = min(_length_score(prompt) * 0.3, 3.0)  # up to 3 bonus points
    especificacion = round(min(spec_keyword + spec_length_bonus, 10.0), 2)

    # --- Criticidad ---
    criticidad = _keyword_score(prompt, CRITICALITY_KEYWORDS)

    # --- Tamaño de respuesta esperado ---
    long_score = _keyword_score(prompt, LONG_RESPONSE_KEYWORDS)
    short_score = _keyword_score(prompt, SHORT_RESPONSE_KEYWORDS)
    # Baseline from prompt length (longer prompt → likely longer answer)
    base_length = _length_score(prompt) * 0.5  # up to 5 base points
    tamano_raw = base_length + long_score - short_score
    tamano_respuesta = round(max(0.0, min(tamano_raw, 10.0)), 2)

    return {
        "concretitud": concreteness,
        "especificacion": especificacion,
        "criticidad": criticidad,
        "tamano_respuesta": tamano_respuesta,
    }


# ---------------------------------------------------------------------------
# Model weight matrix
# Each weight (1-3) reflects how good the model is at handling queries
# with a high score in that dimension. Higher weight = better fit.
#
# Rankings supplied by the user:
#   Criticidad:  Mistral(3) > Groq(2) > Llama(1)
#   Especific.:  Groq(3)    > Mistral(2) > Llama(1)
#   Concretitud: Groq(3)    > Mistral(2) > Llama(1)
#   Largas:      Groq(3)    > Mistral(2) > Llama(1)
#   Cortas:      Llama(3)   > Groq(2)   > Mistral(1)
# ---------------------------------------------------------------------------

MODEL_WEIGHTS = {
    "mistral:7b": {
        "criticidad":    30.0,   # Best at critical/urgent queries
        "especificacion": 2.5,  # Second after Groq
        "concretitud":   2.5,   # Second after Groq
        "tamano_largo":  2.0,   # Second after Groq (long responses)
        "tamano_corto":  1.5,   # Worst at short/simple queries
    },
    "llama-3.1-8b-instant": {   # Groq
        "criticidad":    2.0,   # Second after Mistral
        "especificacion": 3.0,  # Best at technical/specific queries
        "concretitud":   3.0,   # Best at concrete/instructional queries
        "tamano_largo":  2.5,   # Best at long-response queries
        "tamano_corto":  1.5,   # Second at short/simple queries
    },
    "llama3.2:3b": {            # Llama local
        "criticidad":    1.0,   # Worst for critical queries
        "especificacion": 1.0,  # Worst for technical queries
        "concretitud":   1.0,   # Worst for concrete queries
        "tamano_largo":  1.0,   # Worst for long responses
        "tamano_corto":  5.0,   # Best for short/simple queries
    },
}


def compute_raw_model_score(query_scores: dict, model: str) -> float:
    """
    Computes a raw, unnormalized fitness score for a given model based on the
    query's analyzed characteristics.
    """
    weights = MODEL_WEIGHTS.get(model)
    if weights is None:
        return 0.0

    criticidad    = query_scores.get("criticidad", 0.0)
    especificacion = query_scores.get("especificacion", 0.0)
    concretitud   = query_scores.get("concretitud", 0.0)
    tamano        = query_scores.get("tamano_respuesta", 0.0)
    tamano_corto  = round(10.0 - tamano, 2)

    raw = (
        weights.get("criticidad", 1.0)     * criticidad    +
        weights.get("especificacion", 1.0) * especificacion +
        weights.get("concretitud", 1.0)    * concretitud   +
        weights.get("tamano_largo", 1.0)   * tamano        +
        weights.get("tamano_corto", 1.0)   * tamano_corto
    )

    return raw


# ---------------------------------------------------------------------------
# Post-processing: normalize per-query metrics and compute composite score
# ---------------------------------------------------------------------------

def _dynamic_weights(query_scores: dict) -> tuple:
    """
    Returns (w_fit, w_latency, w_cost) adjusted by query characteristics.
    """
    w_fit, w_latency, w_cost = 0.50, 0.10, 0.25

    criticidad     = query_scores.get("criticidad", 0.0)
    tamano         = query_scores.get("tamano_respuesta", 0.0)
    especificacion = query_scores.get("especificacion", 0.0)

    if criticidad > 6:
        w_fit     += 0.10
        w_latency += 0.10
        w_cost    -= 0.20

    if tamano > 7:
        w_cost    += 0.10
        w_latency -= 0.10

    if especificacion > 6:
        w_fit     += 0.10
        w_cost    -= 0.05
        w_latency -= 0.05

    w_fit     = max(0.05, min(0.70, w_fit))
    w_latency = max(0.05, min(0.70, w_latency))
    w_cost    = max(0.05, min(0.70, w_cost))

    total = w_fit + w_latency + w_cost
    return w_fit / total, w_latency / total, w_cost / total


def compute_composite_score(
    query_scores: dict,
    fit_score: float,
    latency_score: float,
    cost_score: float,
) -> float:
    """
    Computes a composite optimality score (0-10) for a model on a specific query.
    """
    w_fit, w_latency, w_cost = _dynamic_weights(query_scores)
    raw = w_fit * fit_score + w_latency * latency_score + w_cost * cost_score
    return round(raw, 2)


def normalize_and_score_results(results: list) -> list:
    """
    Post-processes a list of benchmark result dicts (as saved in resultados.json).
    Computes latency_score, cost_score, score_final, composite_score and modelo_optimo.
    """
    query_groups = {}
    for entry in results:
        q = entry.get("query", "")
        query_groups.setdefault(q, []).append(entry)

    for query_text, group in query_groups.items():
        successful = [e for e in group if e.get("status_code") == 200]

        latencies = [e["latency_s"] for e in successful] or [0]
        costs     = [e["cost"]      for e in successful] or [0]

        max_lat, min_lat = max(latencies), min(latencies)
        max_cost, min_cost = max(costs), min(costs)
        lat_range  = max_lat  - min_lat  or 1e-9
        cost_range = max_cost - min_cost or 1e-9

        # Pre-calculate raw fit scores for this query group to normalize across models
        raw_fits = {}
        for entry in group:
            if "query_scores" not in entry:
                entry["query_scores"] = analyze_query(query_text)
            model = entry.get("model", "")
            raw_fits[model] = compute_raw_model_score(entry["query_scores"], model)
            
        max_raw_fit = max(raw_fits.values()) if raw_fits else 1.0
        if max_raw_fit == 0:
            max_raw_fit = 1.0

        for entry in group:
            qs = entry["query_scores"]
            model = entry.get("model", "")

            if entry.get("status_code") != 200:
                entry["latency_score"]   = 0.0
                entry["cost_score"]      = 0.0
                entry["score_final"]     = 0.0
                entry["composite_score"] = 0.0
                continue

            lat_score = round((max_lat - entry["latency_s"]) / lat_range * 10.0, 2)
            cost_sc = round((max_cost - entry["cost"]) / cost_range * 10.0, 2)

            # Normalize fit score relative to the best model for this specific query
            fit_sc = round((raw_fits[model] / max_raw_fit) * 10.0, 2)
            
            comp_sc = compute_composite_score(qs, fit_sc, lat_score, cost_sc)

            entry["latency_score"]   = lat_score
            entry["cost_score"]      = cost_sc
            entry["score_final"]     = fit_sc
            entry["composite_score"] = comp_sc

        if successful:
            best = max(successful, key=lambda e: e.get("composite_score", 0.0))
            for entry in group:
                entry["modelo_optimo"] = (entry is best)

    return results


# ---------------------------------------------------------------------------
# CLI Action: Update resultados.json
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import os

    json_path = os.path.join(os.path.dirname(__file__), "resultados.json")
    
    if os.path.exists(json_path):
        print(f"Loading {json_path}...")
        with open(json_path, "r", encoding="utf-8") as f:
            results = json.load(f)
            
        print(f"Recalculating scores for {len(results)} entries using current MODEL_WEIGHTS...")
        results = normalize_and_score_results(results)
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
            
        print("Successfully updated resultados.json with new scores!")
    else:
        print(f"Error: {json_path} not found.")

