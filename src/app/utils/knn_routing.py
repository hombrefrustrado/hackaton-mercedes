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
TRAIN_INDICES = [49, 26, 48, 17, 36, 21, 13, 54, 38, 8, 56, 55, 5, 23, 33, 57, 6, 1, 32, 28, 29, 58, 22, 31, 46, 11, 15, 37, 2, 14, 4, 19, 25, 27, 53, 10, 3, 35, 40, 9, 45, 16, 43, 41, 51, 7, 24]

def init_knn():
    global _KNN_MODEL, _X_TRAIN, _MEDIANS
    if _KNN_MODEL is not None:
        return
        
    try:
        # Load the KNN classifier
        model_path = os.path.join(os.path.dirname(__file__), "modelo_knn_ej8.joblib")
        _KNN_MODEL = joblib.load(model_path)
        
        # Load outcomes dataset to reconstruct X_train
        results_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "testing", "mejores_resultados.json")
        df = pd.read_json(results_path)
        X_full = df.drop(columns=["latency_s", "query"])
        
        # Median imputation for training numerical NaNs
        columnas_numericas = X_full.select_dtypes(include=[np.number]).columns
        _MEDIANS = X_full[columnas_numericas].median()
        X_full[columnas_numericas] = X_full[columnas_numericas].fillna(_MEDIANS)
        
        # Ensure correct object type for categorical columns
        for col in X_full.columns:
            if not pd.api.types.is_numeric_dtype(X_full[col]):
                X_full[col] = X_full[col].astype(object)
                
        # Slice X_train using the same 47 indices used to train the classifier
        _X_TRAIN = X_full.iloc[TRAIN_INDICES].copy()
        logger.info("KNN classifier and X_train successfully loaded and cached in memory.")
    except Exception as e:
        logger.error(f"Failed to initialize KNN routing: {e}")

def predict_knn_model(role_name: str, prompt_tokens: int, concretitud, especificacion, criticidad, tamano_respuesta=None) -> str:
    """Predicts the best model using the loaded KNN classifier and Gower distance."""
    init_knn()
    
    # Fallback if model failed to load
    if _KNN_MODEL is None or _X_TRAIN is None:
        logger.warning("KNN routing not initialized. Falling back to llama3.2:3b.")
        return "llama3.2:3b"
        
    try:
        # Fill missing features using training set medians
        if tamano_respuesta is None:
            tamano_respuesta = float(_MEDIANS.get("tamano_respuesta", 5.0))
            
        # Build single row test instance matching X_train schema
        df_test = pd.DataFrame([{
            "departamento": role_name.lower(),
            "model": "llama3.2:3b",  # dummy value matching feature space
            "prompt_tokens": int(prompt_tokens),
            "concretitud": concretitud,
            "especificacion": especificacion,
            "criticidad": criticidad,
            "tamano_respuesta": tamano_respuesta
        }])
        
        # Convert departamento and model to object type
        df_test["departamento"] = df_test["departamento"].astype(object)
        df_test["model"] = df_test["model"].astype(object)
        
        # Calculate Gower distance matrix against training data
        dist_matrix = gower.gower_matrix(df_test, _X_TRAIN)
        
        # Run classification
        prediction = _KNN_MODEL.predict(dist_matrix)[0]
        return str(prediction)
    except Exception as e:
        logger.error(f"Error running KNN prediction: {e}. Falling back to llama3.2:3b.")
        return "llama3.2:3b"
