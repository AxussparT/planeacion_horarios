import numpy as np
import textwrap
import mysql.connector
from src.conexion import get_conexion

# Configuraciones globales
intervalos = 30
n_columnas = 8

# Variables dinámicas para almacenar el estado actual
tensor_actual = None
entidades_actuales = [] # Guardará [Nombre, Indice] (ej. ["f19", 0], ["ALEXIS MARTINEZ", 1])
modo_actual = "Salón"

def obtener_datos_servidor(modo):
    conn = get_conexion()
    if not conn: return [], {}, {}
    cursor = conn.cursor(dictionary=True)

    SEGUNDOS_7AM = 25200
    SEGUNDOS_MEDIA_HORA = 1800
    mapeo_dias = {"Lunes": 1, "Martes": 2, "Miércoles": 3, "Jueves": 4, "Viernes": 5, "Sábado": 6}

    try:
        dict_entidades = {}
        nombres_entidades = {}

        # 1. Definir qué lista de entidades vamos a procesar
        if modo == "Salón":
            cursor.execute("SELECT salon_id AS id FROM salones ORDER BY salon_id")
        elif modo == "Profesor":
            cursor.execute("SELECT profesor_id AS id, nombre AS desc_nombre FROM profesores ORDER BY nombre")
        elif modo == "Grupo":
            cursor.execute("SELECT grupo_id AS id FROM grupos ORDER BY grupo_id")

        regs = cursor.fetchall()
        for i, reg in enumerate(regs):
            dict_entidades[reg['id']] = i
            nombres_entidades[reg['id']] = reg.get('desc_nombre', reg['id'])

        if not dict_entidades: return [], {}, {}

        # 2. Extraer todos los horarios
        query = """
            SELECT h.horario_id, h.salon_id, h.dia, h.hora_inicio, h.hora_fin,
                   a.profesor_id, a.grupo_id, m.nombre AS materia,
                   p.nombre AS profesor_nombre
            FROM horarios h
            JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
            JOIN materias m ON a.materia_id = m.materia_id
            JOIN profesores p ON a.profesor_id = p.profesor_id
        """
        cursor.execute(query)

        verdadero_horario = []
        for reg in cursor.fetchall():
            dia_col = mapeo_dias.get(reg['dia'], 0)
            if dia_col == 0: continue

            idx_i = int((reg['hora_inicio'].total_seconds() - SEGUNDOS_7AM) / SEGUNDOS_MEDIA_HORA) + 1
            idx_f = int((reg['hora_fin'].total_seconds() - SEGUNDOS_7AM) / SEGUNDOS_MEDIA_HORA) + 1

            # Determinar a quién pertenece este horario según el modo
            entidad_id = reg['salon_id'] if modo == "Salón" else (reg['profesor_id'] if modo == "Profesor" else reg['grupo_id'])
            idx_entidad = dict_entidades.get(entidad_id)

            if idx_entidad is None: continue

            # Abreviar materia y nombre para que quepan
            mat_corta = textwrap.shorten(reg['materia'], width=22, placeholder="...")
            prof_partes = reg['profesor_nombre'].split()
            prof_limpio = " ".join(prof_partes[-3:]) if len(prof_partes) > 3 else reg['profesor_nombre']

            # Formatear el texto de la celda según la vista elegida
            if modo == "Salón":
                texto_celda = f"{mat_corta}\n{prof_limpio}\n{reg['grupo_id']}"
            elif modo == "Profesor":
                texto_celda = f"{mat_corta}\nSalón: {reg['salon_id']}\nGrupo: {reg['grupo_id']}"
            elif modo == "Grupo":
                texto_celda = f"{mat_corta}\n{prof_limpio}\nSalón: {reg['salon_id']}"

            verdadero_horario.append([texto_celda, idx_entidad, dia_col, idx_i, idx_f])

        return verdadero_horario, dict_entidades, nombres_entidades
        
    except Exception as e:
        print(f"Error BD en memoria gráfica: {e}")
        return [], {}, {}
    finally:
        cursor.close()
        conn.close()

def inicializar_y_llenar_tensor(modo="Salón"):
    """Recrea el tensor dinámicamente según el modo seleccionado"""
    global tensor_actual, entidades_actuales, modo_actual
    modo_actual = modo

    datos_clases, dict_entidades, nombres_entidades = obtener_datos_servidor(modo)

    n_entidades = max(len(dict_entidades), 1)
    tensor_actual = np.full((n_entidades, intervalos, n_columnas), "", dtype='object')
    entidades_actuales = []

    for ent_id, ent_idx in dict_entidades.items():
        nombre_mostrar = nombres_entidades[ent_id]
        entidades_actuales.append([nombre_mostrar, ent_idx])

        hora_actual = 7.0
        for f in range(1, intervalos):
            h_i = int(hora_actual)
            m_i = "30" if (hora_actual % 1 != 0) else "00"
            hora_sig = hora_actual + 0.5
            h_f = int(hora_sig)
            m_f = "30" if (hora_sig % 1 != 0) else "00"
            tensor_actual[ent_idx, f, 0] = f"{h_i}:{m_i} - {h_f}:{m_f}"
            hora_actual = hora_sig

    for clase in datos_clases:
        texto_celda, ent_idx, dia_col, h_ini, h_fin = clase
        for fila_hora in range(h_ini, h_fin):
            if ent_idx < n_entidades and fila_hora < intervalos:
                tensor_actual[ent_idx, fila_hora, dia_col] = texto_celda