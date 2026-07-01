import os
import joblib
import pandas as pd
import numpy as np
import gower
import logging

logger = logging.getLogger("finops_proxy.knn_routing")

# Global variables for cached model and training set
_KNN_MODEL = None
_X_TRAIN = None
_MEDIANS = None

# Indices from the reverse-engineered training set
TRAIN_INDICES = [27, 39, 103, 121, 129, 99, 20, 14, 107, 101, 21, 4, 178, 116, 65, 84, 43, 87, 85, 56, 175, 127, 156, 23, 51, 164, 148, 106, 61, 9, 35, 89, 42, 75, 72, 114, 137, 91, 163, 128, 123, 92, 47, 126, 176, 143, 18, 68, 133, 5, 122, 31, 76, 168, 93, 161, 22, 34, 38, 141, 3, 117, 24, 124, 146, 53, 49, 41, 125, 50, 111, 171, 158, 71, 13, 108, 100, 0, 109, 46, 33, 145, 19, 12, 130, 147, 25, 142, 70, 79, 144, 10, 40, 179, 115, 1, 136, 64, 96, 73, 170, 139, 86, 77, 119, 95, 102, 169, 118, 66, 2, 67, 6, 149, 105, 113, 8, 88, 7, 104, 138, 58, 120, 162, 98, 69, 11, 112, 63, 134, 29, 26, 97, 159, 165, 17, 140, 60, 54, 59, 81, 153, 154, 132]

def init_knn():
    global _KNN_MODEL, _X_TRAIN, _MEDIANS
    if _KNN_MODEL is not None:
        return
        
    try:
        # Load the KNN classifier
        model_path = os.path.join(os.path.dirname(__file__), "modelo_knn_ej8.joblib")
        _KNN_MODEL = joblib.load(model_path)
        
        # Load outcomes dataset to reconstruct X_train
        results_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "testing", "resultados.json")
        df = pd.read_json(results_path)
        X_full = df.drop(columns=["model", "usuario", "response_preview", "query", "status_code"])
        
        # Median imputation for training numerical NaNs
        columnas_numericas = X_full.select_dtypes(include=[np.number]).columns
        _MEDIANS = X_full[columnas_numericas].median()
        X_full[columnas_numericas] = X_full[columnas_numericas].fillna(_MEDIANS)
        
        # Ensure correct object type for categorical columns
        for col in X_full.columns:
            if not pd.api.types.is_numeric_dtype(X_full[col]):
                X_full[col] = X_full[col].astype(object)
                
        # Slice X_train using the same 144 indices used to train the classifier
        _X_TRAIN = X_full.iloc[TRAIN_INDICES].copy()
        logger.info("KNN classifier and X_train successfully loaded and cached in memory.")
    except Exception as e:
        logger.error(f"Failed to initialize KNN routing: {e}")

def predict_knn_model(role_name: str, prompt_tokens: int) -> str:
    """Predicts the best model using the loaded KNN classifier and Gower distance."""
    init_knn()
    
    # Fallback if model failed to load
    if _KNN_MODEL is None or _X_TRAIN is None:
        logger.warning("KNN routing not initialized. Falling back to llama3.2:3b.")
        return "llama3.2:3b"
        
    try:
        # Fill missing features using training set medians
        median_latency = float(_MEDIANS["latency_s"])
        median_completion = float(_MEDIANS["completion_tokens"])
        median_cost = float(_MEDIANS["cost"])
        
        # Build single row test instance matching X_train schema
        df_test = pd.DataFrame([{
            "departamento": role_name.lower(),
            "latency_s": median_latency,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": median_completion,
            "total_tokens": int(prompt_tokens) + median_completion,
            "cost": median_cost
        }])
        
        # Convert departamento to object type
        df_test["departamento"] = df_test["departamento"].astype(object)
        
        # Calculate Gower distance matrix against training data
        dist_matrix = gower.gower_matrix(df_test, _X_TRAIN)
        
        # Run classification
        prediction = _KNN_MODEL.predict(dist_matrix)[0]
        return str(prediction)
    except Exception as e:
        logger.error(f"Error running KNN prediction: {e}. Falling back to llama3.2:3b.")
        return "llama3.2:3b"
