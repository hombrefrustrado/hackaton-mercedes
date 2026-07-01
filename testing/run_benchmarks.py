import os
import json
import time
import httpx
import sys

# Pricing rates per token (price per 1,000,000 / 1,000,000)
PRICING = {
    "llama3.2:3b": {"input": 0.06 / 1_000_000, "output": 0.06 / 1_000_000},
    "mistral:7b": {"input": 0.24 / 1_000_000, "output": 0.24 / 1_000_000},
    "llama-3.1-8b-instant": {"input": 0.05 / 1_000_000, "output": 0.08 / 1_000_000}
}

DEPT_TO_USER = {
    "marketing": "ana",
    "desarrollo": "carlos",
    "RRHH": "paco"
}

def calculate_cost(model, prompt_tokens, completion_tokens):
    rates = PRICING.get(model, {"input": 0.0, "output": 0.0})
    return (prompt_tokens * rates["input"]) + (completion_tokens * rates["output"])

def run_benchmarks(limit_per_dept=None, max_tokens=15):
    # Load questions
    questions_file = os.path.join(os.path.dirname(__file__), "preguntas.json")
    if not os.path.exists(questions_file):
        print(f"Error: {questions_file} not found.")
        sys.exit(1)
        
    with open(questions_file, "r", encoding="utf-8") as f:
        questions = json.load(f)
        
    # Group and filter if limit is set
    if limit_per_dept is not None:
        filtered_questions = []
        counts = {}
        for q in questions:
            dept = q.get("departamento", "unknown")
            counts[dept] = counts.get(dept, 0)
            if counts[dept] < limit_per_dept:
                filtered_questions.append(q)
                counts[dept] += 1
        questions = filtered_questions

    models = ["llama3.2:3b", "mistral:7b", "llama-3.1-8b-instant"]
    results = []
    
    total_runs = len(questions) * len(models)
    current_run = 0
    
    print(f"Starting benchmark for {len(questions)} queries across {len(models)} models ({total_runs} total requests)...")
    print(f"Using max_tokens={max_tokens} limit for generation speed.")
    
    for idx, q in enumerate(questions):
        dept = q.get("departamento", "unknown")
        query_text = q.get("query", "").strip()
        if not query_text:
            continue
            
        user = DEPT_TO_USER.get(dept, "default")
        
        for model in models:
            current_run += 1
            print(f"[{current_run}/{total_runs}] Model: {model} | Dept: {dept} | Query: {query_text[:50]}...")
            
            # Request details
            url = f"http://localhost:8000/api/v1/{model}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "x-username": user
            }
            payload = {
                "messages": [{"role": "user", "content": query_text}]
            }
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            
            success = False
            retries = 3
            backoff = 1.0
            
            status_code = None
            response_content = ""
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            cost = 0.0
            latency_s = 0.0
            
            while retries > 0 and not success:
                start_time = time.time()
                try:
                    with httpx.Client(timeout=60.0) as client:
                        response = client.post(url, headers=headers, json=payload)
                        latency_s = time.time() - start_time
                        status_code = response.status_code
                        
                        if response.status_code == 200:
                            resp_json = response.json()
                            
                            # Extract completion content
                            choices = resp_json.get("choices", [])
                            if choices:
                                response_content = choices[0].get("message", {}).get("content", "")
                                
                            # Extract usage
                            usage = resp_json.get("usage", {})
                            prompt_tokens = usage.get("prompt_tokens", 0)
                            completion_tokens = usage.get("completion_tokens", 0)
                            total_tokens = usage.get("total_tokens", 0)
                            
                            cost = calculate_cost(model, prompt_tokens, completion_tokens)
                            success = True
                        elif response.status_code == 429:
                            print(f"  [429 Too Many Requests] Retrying in {backoff}s...")
                            time.sleep(backoff)
                            retries -= 1
                            backoff *= 2
                        else:
                            # Other HTTP error (e.g. 402 payment required / budget limit)
                            response_content = response.text
                            print(f"  Error {response.status_code}: {response_content[:150]}")
                            break
                except Exception as e:
                    latency_s = time.time() - start_time
                    response_content = str(e)
                    print(f"  Request exception: {e}. Retrying...")
                    time.sleep(backoff)
                    retries -= 1
                    backoff *= 2
            
            results.append({
                "departamento": dept,
                "usuario": user,
                "query": query_text,
                "model": model,
                "status_code": status_code,
                "latency_s": latency_s,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost": cost,
                "response_preview": response_content[:200]
            })
            
            # Short sleep between requests to avoid rate limits
            time.sleep(0.3)

    # Save results to resultados.json
    output_file = os.path.join(os.path.dirname(__file__), "resultados.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        
    print(f"\nDone! Results saved to {output_file}")
    
    # Print summary table using pandas
    try:
        import pandas as pd
        df = pd.DataFrame(results)
        if not df.empty:
            summary = df.groupby("model").agg(
                requests=("query", "count"),
                avg_latency_s=("latency_s", "mean"),
                total_prompt_tokens=("prompt_tokens", "sum"),
                total_completion_tokens=("completion_tokens", "sum"),
                total_cost=("cost", "sum")
            )
            print("\n=== Benchmark Summary ===")
            print(summary.to_string())
    except Exception as e:
        print(f"Could not print summary table: {e}")

if __name__ == "__main__":
    limit = None
    max_tok = 15
    
    if len(sys.argv) > 1:
        val = sys.argv[1]
        if val.lower() != "all":
            try:
                limit = int(val)
            except ValueError:
                pass
                
    if len(sys.argv) > 2:
        try:
            max_tok = int(sys.argv[2])
            if max_tok <= 0:
                max_tok = None
        except ValueError:
            pass
            
    run_benchmarks(limit_per_dept=limit, max_tokens=max_tok)
