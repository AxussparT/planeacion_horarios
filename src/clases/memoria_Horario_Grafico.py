import numpy as np
import mysql.connector
from src.conexion import get_conexion
import textwrap

# --- CONFIGURACIÓN GLOBAL ---
n_salones = 10  
intervalos = 23
n_columnas = 8  

# Creación del tensor con el nombre original
tensor = np.full((n_salones, intervalos, n_columnas), "", dtype='object')

# MATRIZ GLOBAL DE SALONES
salones_num = []

def obtener_datos_servidor():
    """Ejecuta las consultas y retorna los datos procesados para el tensor."""
    conn = get_conexion()
    cursor = conn.cursor()
    
    SEGUNDOS_7AM = 25200
    SEGUNDOS_MEDIA_HORA = 1800
    mapeo_dias = {"Lunes": 1, "Martes": 2, "Miércoles": 3, "Jueves": 4, "Viernes": 5, "Sábado": 6}

    try:
        cursor.execute("SELECT salon_id FROM salones ORDER BY salon_id")
        regs_salones = cursor.fetchall()
        dict_salones = {reg[0]: i for i, reg in enumerate(regs_salones)}

        # --- MEJORA: LIMPIEZA Y FORMATO DE TEXTO ---
        query_m = """
            SELECT a.asignacion_id, m.nombre AS materia, p.nombre AS profesor, a.grupo_id
            FROM asignaciones a
            JOIN materias m ON a.materia_id = m.materia_id
            JOIN profesores p ON a.profesor_id = p.profesor_id
        """
        cursor.execute(query_m)
        
        dict_materias = {}
        for reg in cursor.fetchall():
            asig_id, m_nom, p_nom, g_id = reg
            
            # 1. Abreviar la materia si es muy larga (ej. máximo 20 caracteres)
            mat_corta = textwrap.shorten(m_nom, width=22, placeholder="...")
            
            # 2. Limpiar el nombre del profe (Truco: tomar solo las últimas 3 palabras para saltar los títulos)
            partes_nombre = p_nom.split()
            if len(partes_nombre) > 3:
                # "DR. EN C. YANET HERNANDEZ" -> se convierte en "YANET HERNANDEZ"
                prof_limpio = " ".join(partes_nombre[-3:])
            else:
                prof_limpio = p_nom
                
            # 3. Formatear la celda con el texto más limpio
            texto_celda = f"{mat_corta}\n {prof_limpio}\n{g_id}"
            dict_materias[asig_id] = texto_celda

        # Consulta de Horarios (El resto sigue igual...)
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
    
    # Obtención de datos frescos de la BD
    datos_clases, salones_info = obtener_datos_servidor()

    # 1. Inicializar etiquetas y matriz global
    for s_id, s_idx in salones_info.items():
        if s_idx < n_salones:
            salones_num.append([s_id, s_idx])
            
            # Fila 0: Encabezado del Salón
            tensor[s_idx, 0, 0] = f"SALÓN {s_id}"  # Cambiado para mostrar el nombre real del salón (ej. f19)
            
            # --- AJUSTE DE ETIQUETAS DE RANGO ---
            hora_actual = 7.0
            for f in range(1, intervalos):
                h_i = int(hora_actual)
                m_i = "30" if (hora_actual % 1 != 0) else "00"
                
                hora_siguiente = hora_actual + 0.5
                h_f = int(hora_siguiente)
                m_f = "30" if (hora_siguiente % 1 != 0) else "00"
                
                tensor[s_idx, f, 0] = f"{h_i}:{m_i} - {h_f}:{m_f}"
                hora_actual = hora_siguiente

    # 2. Llenado de materias con el nuevo formato completo
    for clase in datos_clases:
        texto_celda, s_idx, dia_col, h_ini, h_fin, _ = clase
        
        for fila_hora in range(h_ini, h_fin):
            if s_idx < n_salones and fila_hora < intervalos:
                tensor[s_idx, fila_hora, dia_col] = texto_celda

    print("Sincronización exitosa: Tensor actualizado con datos completos.")