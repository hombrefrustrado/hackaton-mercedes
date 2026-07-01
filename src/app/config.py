import os

# Provider URLs with local machine fallbacks
PROVIDER_A_URL = os.getenv("PROVIDER_A_URL", "http://localhost:11434/v1")
PROVIDER_B_URL = os.getenv("PROVIDER_B_URL", "http://localhost:11435/v1")
PROVIDER_C_URL = os.getenv("PROVIDER_C_URL", "https://api.groq.com/openai/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Pricing rates per 1,000,000 tokens
PRICING = {
    "llama3.2:3b": {"input": 0.06, "output": 0.06},
    "mistral:7b": {"input": 0.24, "output": 0.24},
    "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08}
}

# SQLite DB File path (stored inside src/app/)
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finops_db.sqlite")
