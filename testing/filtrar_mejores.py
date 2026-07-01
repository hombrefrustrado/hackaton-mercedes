import json
import os

def main():
    base_dir = os.path.dirname(__file__)
    input_file = os.path.join(base_dir, "resultados.json")
    output_file = os.path.join(base_dir, "mejores_resultados.json")
    
    if not os.path.exists(input_file):
        print(f"Error: No se encuentra el archivo {input_file}")
        return
        
    with open(input_file, "r", encoding="utf-8") as f:
        resultados = json.load(f)
        
    mejores = []
    
    # Lista de claves a eliminar según tu petición
    keys_to_remove = [
        "status_code", "usuario", "completion_tokens", "total_tokens", 
        "cost", "response", "latency_score", "cost_score", 
        "score_final", "composite_score", "modelo_optimo"
    ]
    
    for entry in resultados:
        # Quedarnos solo con los ganadores
        if entry.get("modelo_optimo") is True:
            # Crear una copia para no modificar el diccionario original directamente
            clean_entry = entry.copy()
            
            # Eliminar las claves no deseadas
            for k in keys_to_remove:
                clean_entry.pop(k, None)
                
            mejores.append(clean_entry)
            
    # Guardar en el nuevo archivo
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(mejores, f, indent=2, ensure_ascii=False)
        
    print(f"Filtrado completado. Se han guardado {len(mejores)} resultados óptimos en {output_file}")

if __name__ == "__main__":
    main()
