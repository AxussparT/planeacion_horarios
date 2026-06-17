import numpy as np
import mysql.connector
import re
from src.conexion import get_conexion

GRUPOS_POR_SEMESTRE = {
    "1": ["S1A", "S1B", "S1C", "S1D", "S1E", "S1F"],
    "2": ["S2A", "S2B", "S2C", "S2D", "S2E", "S2F"],
    "3": ["S3", "S4", "SE", "SF", "SU", "SV"],
    "4": ["S4A", "S4B", "S4C", "S4D", "S4E"],
    "5": ["S5", "S6", "SG", "SH", "ST"],
    "6": ["S6A", "S6B", "S6C", "S6D"],
    "7": ["S7", "S8", "SI", "SJ"],
    "8": ["S8A", "S8B", "S8C"],
    "9": ["S9", "SX", "SW"]
}

def _semestre_de_grupo(grupo_id):
    m = re.match(r'S(\d)', str(grupo_id))
    if m:
        return m.group(1)
    for sem, grupos in GRUPOS_POR_SEMESTRE.items():
        if grupo_id in grupos:
            return sem
    return "0"

class MemoriaHorarioGrafico:
    def __init__(self):
        self.intervalos = 30
        self.n_columnas = 8
        self.tensor = None
        self.entidades = []
        self.modo = "Salón"

    def obtener_datos_servidor(self, modo):
        conn = get_conexion()
        if not conn:
            return [], {}, {}
        cursor = conn.cursor(dictionary=True)

        SEGUNDOS_7AM = 25200
        SEGUNDOS_MEDIA_HORA = 1800
        mapeo_dias = {"Lunes": 1, "Martes": 2, "Miércoles": 3, "Jueves": 4, "Viernes": 5, "Sábado": 6}

        try:
            dict_entidades = {}
            nombres_entidades = {}

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

            if not dict_entidades:
                return [], {}, {}

            query = """
                SELECT h.horario_id, h.salon_id, h.dia, h.hora_inicio, h.hora_fin,
                       a.profesor_id, a.grupo_id, m.nombre AS materia,
                       p.nombre AS profesor_nombre,
                       m.tipo AS materia_tipo, m.semestre_id AS materia_semestre
                FROM horarios h
                JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                JOIN materias m ON a.materia_id = m.materia_id
                JOIN profesores p ON a.profesor_id = p.profesor_id
            """
            cursor.execute(query)

            verdadero_horario = []
            for reg in cursor.fetchall():
                dia_col = mapeo_dias.get(reg['dia'], 0)
                if dia_col == 0:
                    continue

                idx_i = int((reg['hora_inicio'].total_seconds() - SEGUNDOS_7AM) / SEGUNDOS_MEDIA_HORA) + 1
                idx_f = int((reg['hora_fin'].total_seconds() - SEGUNDOS_7AM) / SEGUNDOS_MEDIA_HORA) + 1

                entidad_id = reg['salon_id'] if modo == "Salón" else (reg['profesor_id'] if modo == "Profesor" else reg['grupo_id'])
                idx_entidad = dict_entidades.get(entidad_id)

                if idx_entidad is None:
                    continue

                if modo == "Salón":
                    texto_celda = f"{reg['materia']}\n{reg['profesor_nombre']}\n{reg['grupo_id']}"
                elif modo == "Profesor":
                    texto_celda = f"{reg['materia']}\nSalón: {reg['salon_id']}\nGrupo: {reg['grupo_id']}"
                elif modo == "Grupo":
                    texto_celda = f"{reg['materia']}\n{reg['profesor_nombre']}\nSalón: {reg['salon_id']}"

                verdadero_horario.append([texto_celda, idx_entidad, dia_col, idx_i, idx_f])

                if modo == "Grupo" and reg.get('materia_tipo', '').lower() == 'auditorio':
                    semestre = _semestre_de_grupo(reg['grupo_id'])
                    grupos_semestre = GRUPOS_POR_SEMESTRE.get(semestre, [])
                    for g in grupos_semestre:
                        if g == reg['grupo_id']:
                            continue
                        idx_otro = dict_entidades.get(g)
                        if idx_otro is not None:
                            verdadero_horario.append([texto_celda, idx_otro, dia_col, idx_i, idx_f])

            return verdadero_horario, dict_entidades, nombres_entidades

        except Exception as e:
            print(f"Error BD en memoria gráfica: {e}")
            return [], {}, {}
        finally:
            cursor.close()
            conn.close()

    def inicializar_y_llenar(self, modo="Salón"):
        self.modo = modo
        datos_clases, dict_entidades, nombres_entidades = self.obtener_datos_servidor(modo)

        n_entidades = max(len(dict_entidades), 1)
        self.tensor = np.full((n_entidades, self.intervalos, self.n_columnas), "", dtype='object')
        self.entidades = []

        for ent_id, ent_idx in dict_entidades.items():
            nombre_mostrar = nombres_entidades[ent_id]
            self.entidades.append([nombre_mostrar, ent_idx])

            hora_actual = 7.0
            for f in range(1, self.intervalos):
                h_i = int(hora_actual)
                m_i = "30" if (hora_actual % 1 != 0) else "00"
                hora_sig = hora_actual + 0.5
                h_f = int(hora_sig)
                m_f = "30" if (hora_sig % 1 != 0) else "00"
                self.tensor[ent_idx, f, 0] = f"{h_i}:{m_i} - {h_f}:{m_f}"
                hora_actual = hora_sig

        for clase in datos_clases:
            texto_celda, ent_idx, dia_col, h_ini, h_fin = clase
            for fila_hora in range(h_ini, h_fin):
                if ent_idx < n_entidades and fila_hora < self.intervalos:
                    self.tensor[ent_idx, fila_hora, dia_col] = texto_celda

instancia = MemoriaHorarioGrafico()

intervalos = instancia.intervalos
n_columnas = instancia.n_columnas
tensor_actual = instancia.tensor
entidades_actuales = instancia.entidades
modo_actual = instancia.modo

def obtener_datos_servidor(modo):
    return instancia.obtener_datos_servidor(modo)

def inicializar_y_llenar_tensor(modo="Salón"):
    instancia.inicializar_y_llenar(modo)
    global tensor_actual, entidades_actuales, modo_actual
    tensor_actual = instancia.tensor
    entidades_actuales = instancia.entidades
    modo_actual = instancia.modo