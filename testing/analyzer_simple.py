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
        "criticidad":    3.0,   # Best at critical/urgent queries
        "especificacion": 2.0,  # Second after Groq
        "concretitud":   2.0,   # Second after Groq
        "tamano_largo":  2.0,   # Second after Groq (long responses)
        "tamano_corto":  1.0,   # Worst at short/simple queries
    },
    "llama-3.1-8b-instant": {   # Groq
        "criticidad":    2.0,   # Second after Mistral
        "especificacion": 3.0,  # Best at technical/specific queries
        "concretitud":   3.0,   # Best at concrete/instructional queries
        "tamano_largo":  3.0,   # Best at long-response queries
        "tamano_corto":  2.0,   # Second at short/simple queries
    },
    "llama3.2:3b": {            # Llama local
        "criticidad":    1.0,   # Worst for critical queries
        "especificacion": 1.0,  # Worst for technical queries
        "concretitud":   1.0,   # Worst for concrete queries
        "tamano_largo":  1.0,   # Worst for long responses
        "tamano_corto":  3.0,   # Best for short/simple queries
    },
}


def compute_model_score(query_scores: dict, model: str) -> float:
    """
    Computes a weighted fitness score (0-10) for a given model based on the
    query's analyzed characteristics.

    A higher score means this model is a better fit for the query.

    Args:
        query_scores: Dict returned by analyze_query().
        model:        One of 'mistral:7b', 'llama-3.1-8b-instant', 'llama3.2:3b'.

    Returns:
        A float between 0.0 and 10.0.
    """
    weights = MODEL_WEIGHTS.get(model)
    if weights is None:
        return 0.0

    criticidad    = query_scores.get("criticidad", 0.0)
    especificacion = query_scores.get("especificacion", 0.0)
    concretitud   = query_scores.get("concretitud", 0.0)
    tamano        = query_scores.get("tamano_respuesta", 0.0)
    tamano_corto  = round(10.0 - tamano, 2)   # Inverse: low tamano → good for short-query models

    raw = (
        weights["criticidad"]    * criticidad    +
        weights["especificacion"] * especificacion +
        weights["concretitud"]   * concretitud   +
        weights["tamano_largo"]  * tamano        +
        weights["tamano_corto"]  * tamano_corto
    )

    max_raw = sum(weights.values()) * 10.0
    if max_raw == 0:
        return 0.0

    return round((raw / max_raw) * 10.0, 2)


# ---------------------------------------------------------------------------
# Quick CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    models = ["mistral:7b", "llama-3.1-8b-instant", "llama3.2:3b"]
    samples = [
        "¿Qué es Docker?",
        "Explica exactamente paso a paso cómo configurar un servidor Nginx con SSL en producción.",
        "Urgente: hay un error crítico en producción que está causando pérdida de datos.",
        "Redacta un informe exhaustivo de 1000 palabras sobre estrategias de marketing digital para 2025.",
        "Resume brevemente qué es una API REST.",
    ]
    for s in samples:
        scores = analyze_query(s)
        print(f"\nQuery: {s[:70]}")
        for k, v in scores.items():
            print(f"  {k:20s}: {v:.1f}/10")
        print(f"  {'--- Model fit ---':20s}")
        for m in models:
            fit = compute_model_score(scores, m)
            print(f"  {m:30s}: {fit:.1f}/10")

