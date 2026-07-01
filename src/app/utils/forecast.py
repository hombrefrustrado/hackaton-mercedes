import sqlite3
import pandas as pd
import numpy as np
import datetime
import logging
import os
from ..config import DB_FILE, PRICING

logger = logging.getLogger("finops_proxy.forecast")

def get_forecast_data(role_filter=None):
    conn = sqlite3.connect(DB_FILE)
    # Get all queries
    df_queries = pd.read_sql_query("""
        SELECT q.Fecha as timestamp, q.Usuario as user_id, r.nombre as role_name, q.Modelo as model,
               q.Num_tokens_in as prompt_tokens, q.Num_tokens_out as completion_tokens
        FROM Query q
        JOIN Usuario u ON q.Usuario = u.Email
        JOIN Rol r ON u.rol = r.Id
        JOIN Modelo m ON q.Modelo = m.Nombre
        ORDER BY q.Fecha ASC
    """, conn)
    conn.close()
    
    if df_queries.empty:
        return {
            "history_timestamps": [],
            "history_cumulative": [],
            "forecast_timestamps": [],
            "forecast_cumulative": [],
            "bin_unit": "minute",
            "model_used": "none"
        }
        
    # Convert timestamp to datetime
    df_queries["timestamp"] = pd.to_datetime(df_queries["timestamp"])
    
    # Calculate cost for each query
    def calculate_cost(row):
        model = row["model"]
        rates = PRICING.get(model, {"input": 0.0, "output": 0.0})
        return (row["prompt_tokens"] * rates["input"] + row["completion_tokens"] * rates["output"]) / 1_000_000
        
    df_queries["cost"] = df_queries.apply(calculate_cost, axis=1)
    
    # Filter by role if specified
    if role_filter and role_filter != "todos":
        df_queries = df_queries[df_queries["role_name"].str.lower() == role_filter.lower()]
        if df_queries.empty:
            return {
                "history_timestamps": [],
                "history_cumulative": [],
                "forecast_timestamps": [],
                "forecast_cumulative": [],
                "bin_unit": "minute",
                "model_used": "none"
            }
            
    # Determine bin size dynamically based on time range
    first_time = df_queries["timestamp"].min()
    last_time = df_queries["timestamp"].max()
    time_range = last_time - first_time
    
    if time_range < pd.Timedelta(hours=1):
        bin_unit = "minute"
        freq = "1min"
    elif time_range < pd.Timedelta(days=1):
        bin_unit = "hour"
        freq = "h"
    else:
        bin_unit = "day"
        freq = "D"
        
    # Resample and sum cost
    df_queries.set_index("timestamp", inplace=True)
    df_bins = df_queries["cost"].resample(freq).sum().fillna(0.0)
    
    # If we have only 1 bin, let's create dummy history to allow plotting
    if len(df_bins) < 2:
        # Create a helper sequence
        idx = pd.date_range(end=last_time, periods=3, freq=freq)
        df_bins = pd.Series([0.0, 0.0, df_bins.iloc[0]], index=idx)
        
    # History data points
    history_timestamps = [t.strftime("%Y-%m-%d %H:%M:%S") for t in df_bins.index]
    history_cumulative = df_bins.cumsum().values.tolist()
    
    # Fit ARIMA model on incremental spent per bin
    # We want to forecast the next 7 periods
    n_forecast = 7
    forecast_timestamps = []
    current_time = df_bins.index[-1]
    for _ in range(n_forecast):
        if bin_unit == "minute":
            current_time += datetime.timedelta(minutes=1)
        elif bin_unit == "hour":
            current_time += datetime.timedelta(hours=1)
        else:
            current_time += datetime.timedelta(days=1)
        forecast_timestamps.append(current_time.strftime("%Y-%m-%d %H:%M:%S"))
        
    y = df_bins.values
    model_used = "ARIMA(1,1,0)"
    
    # ARIMA fit and prediction
    # Try statsmodels first
    statsmodels_success = False
    forecast_increments = []
    
    if len(y) >= 10:
        try:
            from statsmodels.tsa.arima.model import ARIMA
            # fit ARIMA(1,1,0) on increments
            model = ARIMA(y, order=(1, 1, 0))
            model_fit = model.fit()
            forecast_increments = model_fit.forecast(steps=n_forecast)
            forecast_increments = np.clip(forecast_increments, 0.0, None).tolist() # clamp to non-negative
            statsmodels_success = True
            model_used = "statsmodels.ARIMA(1,1,0)"
        except Exception as e:
            logger.info(f"Statsmodels ARIMA failed: {e}. Falling back to custom ARIMA.")
            
    if not statsmodels_success:
        # Custom ARIMA(1,1,0) / Autoregressive lag-1 difference fallback
        if len(y) >= 4:
            diffs = np.diff(y)
            diff_mean = 0.0
            
            # Estimate lag-1 autocorrelation (phi) of differences
            diffs_zero_mean = diffs
            var = np.sum(diffs_zero_mean**2)
            if var > 1e-9:
                cov = np.sum(diffs_zero_mean[1:] * diffs_zero_mean[:-1])
                phi = cov / var
                phi = np.clip(phi, -0.8, 0.8)
            else:
                phi = 0.0
                
            # Forecast increments using: diff_t = phi * diff_{t-1}
            last_diff = diffs[-1]
            current_diff = last_diff
            
            last_y_val = y[-1]
            for _ in range(n_forecast):
                current_diff = phi * current_diff
                next_val = last_y_val + current_diff
                # Ensure it doesn't drop below 0
                next_val = max(0.0, next_val)
                forecast_increments.append(next_val)
                last_y_val = next_val
            model_used = "custom.ARIMA(1,1,0)"
        else:
            # Simple average fallback for very small datasets
            mean_val = np.mean(y)
            forecast_increments = [mean_val] * n_forecast
            model_used = "custom.MeanBaseline"
            
    # Calculate cumulative forecast values starting from last cumulative value
    last_cum = float(history_cumulative[-1])
    forecast_cumulative = []
    current_cum = last_cum
    for inc in forecast_increments:
        current_cum += float(inc)
        forecast_cumulative.append(float(current_cum))
        
    return {
        "history_timestamps": history_timestamps,
        "history_cumulative": history_cumulative,
        "forecast_timestamps": forecast_timestamps,
        "forecast_cumulative": forecast_cumulative,
        "bin_unit": bin_unit,
        "model_used": model_used
    }
