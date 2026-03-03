import numpy as np
import mysql.connector
from src.conexion import get_conexion

# --- CONFIGURACIÓN GLOBAL ---
n_salones = 10  
intervalos = 30 
n_columnas = 8  

# Creación del tensor con el nombre original
tensor = np.full((n_salones, intervalos, n_columnas), "", dtype='object')

# MATRIZ GLOBAL DE SALONES (Accesible desde cualquier módulo)
# Contendrá pares: [[id_salon, numero_asignado], ...]
salones_num = []

def obtener_datos_servidor():
    """Ejecuta las consultas y retorna los datos procesados para el tensor."""
    conn = get_conexion()
    cursor = conn.cursor()
    
    SEGUNDOS_7AM = 25200
    SEGUNDOS_MEDIA_HORA = 1800
    mapeo_dias = {"Lunes": 1, "Martes": 2, "Miércoles": 3, "Jueves": 4, "Viernes": 5, "Sábado": 6}

    try:
        # Consulta de Salones
        cursor.execute("SELECT salon_id FROM salones")
        regs_salones = cursor.fetchall()
        
        # Diccionario para mapeo interno
        dict_salones = {reg[0]: i for i, reg in enumerate(regs_salones)}

        # Consulta de Materias
        query_m = """
            SELECT h.asignacion_id, m.nombre 
            FROM horarios h
            JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
            JOIN materias m ON a.materia_id = m.materia_id
        """
        cursor.execute(query_m)
        dict_materias = {reg[0]: reg[1] for reg in cursor.fetchall()}

        # Consulta de Horarios
        cursor.execute("SELECT horario_id, asignacion_id, salon_id, dia, hora_inicio, hora_fin FROM horarios")
        verdadero_horario = []
        for reg in cursor.fetchall():
            h_id, asig_id, s_id, dia_txt, h_ini, h_fin = reg
            idx_i = int((h_ini.total_seconds() - SEGUNDOS_7AM) / SEGUNDOS_MEDIA_HORA) + 1
            idx_f = int((h_fin.total_seconds() - SEGUNDOS_7AM) / SEGUNDOS_MEDIA_HORA) + 1
            
            verdadero_horario.append([
                dict_materias.get(asig_id, "N/A"),
                dict_salones.get(s_id, 0),
                mapeo_dias.get(dia_txt, 0),
                idx_i,
                idx_f,
                s_id 
            ])
        
        return verdadero_horario, dict_salones

    except Exception as e:
        print(f"Error al obtener datos: {e}")
        return [], {}
    finally:
        cursor.close()
        conn.close()

def inicializar_y_llenar_tensor():
    """Limpia y rellena el objeto 'tensor' y la matriz 'salones_num'."""
    global tensor, salones_num
    tensor.fill("") 
    salones_num = [] 
    
    # Obtención de datos
    datos_clases, salones_info = obtener_datos_servidor()

    # 1. Inicializar etiquetas y matriz global
    for s_id, s_idx in salones_info.items():
        if s_idx < n_salones:
            salones_num.append([s_id, s_idx])
            
            # Fila 0: Encabezado del Salón
            tensor[s_idx, 0, 0] = f"SALÓN {s_idx}" 
            
            # --- AJUSTE DE ETIQUETAS DE RANGO ---
            hora_actual = 7.0
            for f in range(1, intervalos):
                # Calcular hora de inicio
                h_i = int(hora_actual)
                m_i = "30" if (hora_actual % 1 != 0) else "00"
                
                # Calcular hora de fin (sumando 30 min)
                hora_siguiente = hora_actual + 0.5
                h_f = int(hora_siguiente)
                m_f = "30" if (hora_siguiente % 1 != 0) else "00"
                
                # Guardar el rango completo en la primera columna
                tensor[s_idx, f, 0] = f"{h_i}:{m_i} - {h_f}:{m_f}"
                
                hora_actual = hora_siguiente

    # 2. Llenado de materias (mantenemos la lógica que ya te funcionaba)
    for clase in datos_clases:
        nombre_materia, s_idx, dia_col, h_ini, h_fin, _ = clase
        
        for fila_hora in range(h_ini, h_fin):
            if s_idx < n_salones and fila_hora < intervalos:
                tensor[s_idx, fila_hora, dia_col] = nombre_materia

    print("Sincronización exitosa: Horas mostradas como rangos (inicio - fin).")

# Ejecución inicial
if __name__ == "__main__":
    inicializar_y_llenar_tensor()
    print("Sincronización completa.")
    print(f"Matriz Global de Salones: {salones_num}")