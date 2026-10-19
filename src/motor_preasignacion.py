# -*- coding: utf-8 -*-
"""
Motor de Preasignación de Aulas y Horarios (SAGA 2.0)
Asigna materias de cada grupo a salones y horarios SIN profesor:
- 2 grupos por aula estándar de tipo normal (Franja 1: 07:00 a 13:00, Franja 2: 13:00 a 17:00+)
- Empaquetamiento de hasta 3 grupos por aula si son grupos reducidos (< 4 materias)
- Agrupación de materias de 'Laboratorio de computación' en un mismo laboratorio sin dispersión
- Patrones de distribución simétrica basados en motor_horarios_anterior.py
- Generación de asignaciones con estado 'no asignado' y profesor 'SIN_ASIGNAR'
"""

import math
import sqlite3
from src.conexion import get_conexion, obtener_cursor

class GeneradorPreasignacion:
    HORA_BASE = 7  # 07:00 AM es el slot 0
    MINUTOS_SLOT = 30
    TOTAL_SLOTS_DIA = 32  # 07:00 a 23:00

    DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    PAREJAS_DIAS = [
        ("Lunes", "Miércoles"),
        ("Martes", "Jueves"),
        ("Miércoles", "Viernes"),
        ("Lunes", "Jueves"),
        ("Martes", "Viernes"),
        ("Jueves", "Sábado"),
        ("Viernes", "Sábado")
    ]

    TRIADAS_DIAS = [
        ("Lunes", "Miércoles", "Viernes"),
        ("Martes", "Jueves", "Sábado")
    ]

    def __init__(self):
        self.ocupacion_salones = {}   # (salon_id, dia, slot) -> bool
        self.ocupacion_grupos = {}    # (grupo_id, dia, slot) -> bool
        self.salones_normales = []
        self.salones_computo = []
        self.salones_otros = {}       # tipo -> [salon_id, ...]

    @classmethod
    def hora_a_slot(cls, hora_str):
        partes = str(hora_str).split(":")
        h = int(partes[0])
        m = int(partes[1]) if len(partes) > 1 else 0
        slot = (h - cls.HORA_BASE) * 2
        if m >= 30:
            slot += 1
        return max(0, slot)

    @classmethod
    def slot_a_hora(cls, slot):
        min_totales = slot * cls.MINUTOS_SLOT
        hh = cls.HORA_BASE + (min_totales // 60)
        mm = min_totales % 60
        return f"{hh:02d}:{mm:02d}:00"

    def _asegurar_profesor_sin_asignar(self):
        with obtener_cursor() as ctx:
            if ctx:
                cur, conn = ctx
                cur.execute(
                    "INSERT OR IGNORE INTO profesores (profesor_id, no_cuenta, nombre) "
                    "VALUES ('SIN_ASIGNAR', '0000', 'Sin profesor')"
                )

    def cargar_salones(self):
        self.salones_normales.clear()
        self.salones_computo.clear()
        self.salones_otros.clear()

        conn = get_conexion()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT salon_id, capacidad, tipo FROM salones ORDER BY salon_id")
        for row in cur.fetchall():
            s_id = str(row[0])
            if s_id.upper().startswith("MEDIACION_TECNOLOGICA"):
                continue
            tipo_val = row[2] if len(row) > 2 and row[2] is not None else 'Normal'
            t = str(tipo_val).strip().upper()
            if t in ('NORMAL',):
                self.salones_normales.append(s_id)
            elif t in ('TECNOLOGICA', 'TECNOLÓGICA', 'LABORATORIO DE COMPUTACION', 'LABORATORIO DE COMPUTACIÓN'):
                self.salones_computo.append(s_id)
            else:
                self.salones_otros.setdefault(t, []).append(s_id)
        cur.close()
        conn.close()

    def cargar_grupos_y_materias(self, filtro_periodo=None, filtro_semestre=None):
        """
        Retorna lista de grupos con sus materias vinculadas:
        [{
            'grupo_id': '101A',
            'nivel': 1,
            'periodo': 'B',
            'materias': [{'materia_id': 'MAT1', 'nombre': '...', 'horas': 4.0, 'tipo': 'NORMAL'}, ...]
        }, ...]
        """
        conn = get_conexion()
        if not conn:
            return []
        cur = conn.cursor()

        cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY nivel, grupo_id")
        grupos_bd = cur.fetchall()

        resultado = []
        for g_row in grupos_bd:
            g_id = str(g_row[0])
            nivel = g_row[1] if len(g_row) > 1 and g_row[1] is not None else 1
            try:
                nivel_num = int(nivel)
            except ValueError:
                nivel_num = 1

            # Determinar periodo
            periodo = 'A' if nivel_num in (2, 4, 6, 8, 10) else 'B'

            if filtro_periodo and periodo != filtro_periodo:
                continue
            if filtro_semestre and nivel_num != filtro_semestre:
                continue

            # Consultar materias asociadas a través de grupo_materias
            cur.execute("""
                SELECT m.materia_id, m.nombre, m.horas_semana, m.tipo
                FROM grupo_materias gm
                JOIN materias m ON gm.materia_id = m.materia_id
                WHERE gm.grupo_id = %s
                ORDER BY m.tipo, m.materia_id
            """, (g_id,))
            mats = []
            for m_row in cur.fetchall():
                mats.append({
                    'materia_id': str(m_row[0]),
                    'nombre': str(m_row[1]),
                    'horas_semana': float(m_row[2] or 4.0),
                    'tipo': str(m_row[3] or 'NORMAL').strip().upper()
                })

            if mats:
                resultado.append({
                    'grupo_id': g_id,
                    'nivel': nivel_num,
                    'periodo': periodo,
                    'materias': mats
                })

        cur.close()
        conn.close()
        return resultado

    def _es_posible_bloque(self, salon_id, grupo_id, dia, slot_inicio, duracion_slots):
        if slot_inicio + duracion_slots > self.TOTAL_SLOTS_DIA:
            return False
        for s in range(slot_inicio, slot_inicio + duracion_slots):
            if self.ocupacion_salones.get((salon_id, dia, s)):
                return False
            if self.ocupacion_grupos.get((grupo_id, dia, s)):
                return False
        return True

    def _registrar_bloque(self, salon_id, grupo_id, dia, slot_inicio, duracion_slots):
        for s in range(slot_inicio, slot_inicio + duracion_slots):
            self.ocupacion_salones[(salon_id, dia, s)] = True
            self.ocupacion_grupos[(grupo_id, dia, s)] = True

    def _generar_estrategias(self, horas_semana):
        """
        Divide las horas en patrones simétricos de días y slots (30 min cada slot).
        """
        bloques = int(round(horas_semana * 2))
        if bloques <= 0:
            bloques = 4

        estrategias = []
        if bloques >= 6:
            mitad1 = math.ceil(bloques / 2)
            mitad2 = bloques - mitad1
            for d1, d2 in self.PAREJAS_DIAS:
                estrategias.append([(d1, mitad1), (d2, mitad2)])
                if mitad1 != mitad2:
                    estrategias.append([(d1, mitad2), (d2, mitad1)])

            if bloques == 6:
                # 3 sesiones de 1 hora
                for triada in self.TRIADAS_DIAS:
                    estrategias.append([(triada[0], 2), (triada[1], 2), (triada[2], 2)])

            if bloques == 8:
                # 4 sesiones o 2+2+2+2
                for triada in self.TRIADAS_DIAS:
                    estrategias.append([(triada[0], 3), (triada[1], 3), (triada[2], 2)])
        else:
            mitad1 = math.ceil(bloques / 2)
            mitad2 = bloques - mitad1
            if mitad1 > 0 and mitad2 > 0:
                for d1, d2 in self.PAREJAS_DIAS:
                    estrategias.append([(d1, mitad1), (d2, mitad2)])
            for d in self.DIAS_SEMANA:
                estrategias.append([(d, bloques)])

        return estrategias

    def ejecutar(self, filtro_periodo=None, filtro_semestre=None):
        self._asegurar_profesor_sin_asignar()
        self.cargar_salones()
        self.ocupacion_salones.clear()
        self.ocupacion_grupos.clear()

        grupos = self.cargar_grupos_y_materias(filtro_periodo, filtro_semestre)
        if not grupos:
            return {
                "exito": False,
                "mensaje": "No se encontraron grupos con materias asignadas para el periodo/semestre seleccionado."
            }

        if not self.salones_normales:
            return {
                "exito": False,
                "mensaje": "No hay salones de tipo Normal registrados en el sistema."
            }

        # Separar grupos regulares (>= 4 materias) y grupos reducidos (< 4 materias)
        grupos_regulares = [g for g in grupos if len(g['materias']) >= 4]
        grupos_reducidos = [g for g in grupos if len(g['materias']) < 4]

        # Planificación de distribución en salones normales:
        # Cada salón normal puede albergar:
        # 1) 2 grupos regulares (Franja 1: 07:00-13:00, Franja 2: 13:00-19:00+)
        # 2) 1 grupo regular + hasta 2 grupos reducidos
        # 3) hasta 3 grupos reducidos (07:00-11:00, 11:00-15:00, 15:00-19:00)
        asignacion_aulas = {}  # grupo_id -> (salon_normal, slot_min, slot_max)

        idx_salon = 0
        total_salones_norm = len(self.salones_normales)

        # 1. Emparejar grupos regulares en parejas
        i = 0
        while i < len(grupos_regulares):
            g_manana = grupos_regulares[i]
            salon_asignado = self.salones_normales[idx_salon % total_salones_norm]
            # Franja matutina: slot 0 (07:00) a 12 (13:00)
            asignacion_aulas[g_manana['grupo_id']] = (salon_asignado, 0, 12)

            if i + 1 < len(grupos_regulares):
                g_tarde = grupos_regulares[i + 1]
                # Franja vespertina: slot 12 (13:00) a 26 (20:00)
                asignacion_aulas[g_tarde['grupo_id']] = (salon_asignado, 12, 26)
                i += 2
            else:
                # Quedó un grupo regular solo en este salón; si hay reducidos, empaquetar hasta 2 aquí
                if len(grupos_reducidos) >= 2:
                    g_red1 = grupos_reducidos.pop(0)
                    g_red2 = grupos_reducidos.pop(0)
                    asignacion_aulas[g_red1['grupo_id']] = (salon_asignado, 12, 18)
                    asignacion_aulas[g_red2['grupo_id']] = (salon_asignado, 18, 26)
                elif len(grupos_reducidos) == 1:
                    g_red = grupos_reducidos.pop(0)
                    asignacion_aulas[g_red['grupo_id']] = (salon_asignado, 12, 22)
                i += 1

            idx_salon += 1

        # 2. Empaquetar grupos reducidos restantes (hasta 3 por salón)
        while grupos_reducidos:
            salon_asignado = self.salones_normales[idx_salon % total_salones_norm]
            idx_salon += 1

            # Tomar hasta 3 grupos reducidos
            lote_red = []
            for _ in range(min(3, len(grupos_reducidos))):
                lote_red.append(grupos_reducidos.pop(0))

            if len(lote_red) == 3:
                # 3 grupos en el salón: 07:00-11:00, 11:00-15:00, 15:00-19:30
                asignacion_aulas[lote_red[0]['grupo_id']] = (salon_asignado, 0, 8)
                asignacion_aulas[lote_red[1]['grupo_id']] = (salon_asignado, 8, 16)
                asignacion_aulas[lote_red[2]['grupo_id']] = (salon_asignado, 16, 26)
            elif len(lote_red) == 2:
                # 2 grupos en el salón: 07:00-13:00 y 13:00-19:00
                asignacion_aulas[lote_red[0]['grupo_id']] = (salon_asignado, 0, 12)
                asignacion_aulas[lote_red[1]['grupo_id']] = (salon_asignado, 12, 26)
            elif len(lote_red) == 1:
                asignacion_aulas[lote_red[0]['grupo_id']] = (salon_asignado, 0, 16)

        # 3. Asignar laboratorios de cómputo fijos por grupo (Regla 2: no dispersión)
        # Cada grupo que requiera cómputo tendrá UN único salón de cómputo asignado
        laboratorio_por_grupo = {}
        if self.salones_computo:
            idx_lab = 0
            for g in grupos:
                tiene_computo = any(m['tipo'] in ('TECNOLOGICA', 'TECNOLÓGICA', 'LABORATORIO DE COMPUTACION', 'LABORATORIO DE COMPUTACIÓN') for m in g['materias'])
                if tiene_computo:
                    lab_escogido = self.salones_computo[idx_lab % len(self.salones_computo)]
                    laboratorio_por_grupo[g['grupo_id']] = lab_escogido
                    idx_lab += 1

        # 4. Asignación horaria y de salón para cada materia
        horarios_a_guardar = []     # (asig_id, salon_id, dia, hora_i, hora_f)
        asignaciones_a_guardar = [] # dicts con datos para tabla asignaciones
        salones_utilizados = set()
        alertas = []

        for g in grupos:
            g_id = g['grupo_id']
            salon_base, slot_min, slot_max = asignacion_aulas.get(g_id, (self.salones_normales[0], 0, 16))
            salones_utilizados.add(salon_base)
            lab_grupo = laboratorio_por_grupo.get(g_id)

            for mat in g['materias']:
                m_id = mat['materia_id']
                m_nom = mat['nombre']
                m_tipo = mat['tipo']
                h_sem = mat['horas_semana']

                # Salón correspondiente según tipo de materia
                if m_tipo in ('TECNOLOGICA', 'TECNOLÓGICA', 'LABORATORIO DE COMPUTACION', 'LABORATORIO DE COMPUTACIÓN'):
                    salon_objetivo = lab_grupo or (self.salones_computo[0] if self.salones_computo else salon_base)
                elif m_tipo == 'AUDITORIO' and self.salones_otros.get('AUDITORIO'):
                    salon_objetivo = self.salones_otros['AUDITORIO'][0]
                elif m_tipo == 'LABORATORIO' and self.salones_otros.get('LABORATORIO'):
                    salon_objetivo = self.salones_otros['LABORATORIO'][0]
                else:
                    salon_objetivo = salon_base

                salones_utilizados.add(salon_objetivo)

                # Buscar la mejor combinación de días y horarios dentro de la franja asignada al grupo
                estrategias = self._generar_estrategias(h_sem)
                materia_asignada = False
                sesiones_asignadas = []

                # Probar cada estrategia simétrica
                for estrategia in estrategias:
                    # Buscar slot de inicio que funcione para todos los días de la estrategia
                    # Mantenerlo lo más compacto posible al inicio de la franja del grupo
                    duracion_max = max(bloques for _, bloques in estrategia)
                    for slot_prueba in range(slot_min, slot_max - duracion_max + 1):
                        posible_todos = True
                        for dia, duracion in estrategia:
                            if not self._es_posible_bloque(salon_objetivo, g_id, dia, slot_prueba, duracion):
                                posible_todos = False
                                break

                        if posible_todos:
                            # Asignar en este horario
                            for dia, duracion in estrategia:
                                self._registrar_bloque(salon_objetivo, g_id, dia, slot_prueba, duracion)
                                hora_i = self.slot_a_hora(slot_prueba)
                                hora_f = self.slot_a_hora(slot_prueba + duracion)
                                sesiones_asignadas.append({
                                    "dia": dia,
                                    "hora_inicio": hora_i,
                                    "hora_fin": hora_f,
                                    "salon_id": salon_objetivo
                                })
                            materia_asignada = True
                            break

                    if materia_asignada:
                        break

                # Si no cupo simétricamente en el mismo slot, probar slots individuales por día
                if not materia_asignada:
                    for estrategia in estrategias:
                        sesiones_temp = []
                        exito_est = True
                        for dia, duracion in estrategia:
                            encontrado_dia = False
                            for slot_prueba in range(slot_min, slot_max - duracion + 1):
                                if self._es_posible_bloque(salon_objetivo, g_id, dia, slot_prueba, duracion):
                                    hora_i = self.slot_a_hora(slot_prueba)
                                    hora_f = self.slot_a_hora(slot_prueba + duracion)
                                    sesiones_temp.append({
                                        "dia": dia,
                                        "hora_inicio": hora_i,
                                        "hora_fin": hora_f,
                                        "salon_id": salon_objetivo,
                                        "slot": slot_prueba,
                                        "duracion": duracion
                                    })
                                    encontrado_dia = True
                                    break
                            if not encontrado_dia:
                                exito_est = False
                                break

                        if exito_est:
                            for item in sesiones_temp:
                                self._registrar_bloque(item['salon_id'], g_id, item['dia'], item['slot'], item['duracion'])
                                sesiones_asignadas.append({
                                    "dia": item['dia'],
                                    "hora_inicio": item['hora_inicio'],
                                    "hora_fin": item['hora_fin'],
                                    "salon_id": item['salon_id']
                                })
                            materia_asignada = True
                            break

                if materia_asignada and sesiones_asignadas:
                    dias_str = ",".join(s['dia'] for s in sesiones_asignadas)
                    # Hora inicio y fin de referencia
                    hi_ref = min(s['hora_inicio'] for s in sesiones_asignadas)
                    hf_ref = max(s['hora_fin'] for s in sesiones_asignadas)
                    asignaciones_a_guardar.append({
                        "grupo_id": g_id,
                        "materia_id": m_id,
                        "materia_nombre": m_nom,
                        "periodo": g['periodo'],
                        "hora_inicio": hi_ref,
                        "hora_fin": hf_ref,
                        "dias": dias_str,
                        "salon_base": salon_objetivo,
                        "sesiones": sesiones_asignadas
                    })
                else:
                    alertas.append(f"No se encontró espacio libre para {m_nom} en el grupo {g_id}.")

        # 5. Persistir en la base de datos
        total_asignadas = 0
        total_horarios = 0

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "No se pudo conectar a la base de datos para guardar."}
            cur, conn = ctx
            try:
                for asig in asignaciones_a_guardar:
                    g_id = asig['grupo_id']
                    m_id = asig['materia_id']

                    # Limpiar asignaciones previas no asignadas o preexistentes de esa materia y grupo
                    cur.execute(
                        "SELECT asignacion_id FROM asignaciones WHERE grupo_id = %s AND materia_id = %s",
                        (g_id, m_id)
                    )
                    existente = cur.fetchone()
                    if existente:
                        asig_id = existente[0]
                        # Limpiar horarios previos
                        cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                        cur.execute("""
                            UPDATE asignaciones
                            SET profesor_id = 'SIN_ASIGNAR', periodo = %s, hora_inicio = %s,
                                hora_fin = %s, dias = %s, modalidad = 'Presencial', estado = 'no asignado'
                            WHERE asignacion_id = %s
                        """, (asig['periodo'], asig['hora_inicio'], asig['hora_fin'], asig['dias'], asig_id))
                    else:
                        cur.execute("""
                            INSERT INTO asignaciones
                                (profesor_id, materia_id, grupo_id, periodo, hora_inicio, hora_fin, dias, modalidad, estado)
                            VALUES
                                ('SIN_ASIGNAR', %s, %s, %s, %s, %s, %s, 'Presencial', 'no asignado')
                        """, (m_id, g_id, asig['periodo'], asig['hora_inicio'], asig['hora_fin'], asig['dias']))
                        asig_id = cur.lastrowid

                    total_asignadas += 1

                    # Insertar sesiones en horarios
                    for ses in asig['sesiones']:
                        cur.execute("""
                            INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (asig_id, ses['salon_id'], ses['dia'], ses['hora_inicio'], ses['hora_fin']))
                        total_horarios += 1

            except sqlite3.Error as err:
                conn.rollback()
                return {"exito": False, "mensaje": f"Error persistiendo la preasignación: {err}"}

        # Resumen detallado
        resumen_grupos = []
        for g_id, (s_base, s_min, s_max) in asignacion_aulas.items():
            h_inicio = self.slot_a_hora(s_min)[:5]
            h_fin = self.slot_a_hora(s_max)[:5]
            lab = laboratorio_por_grupo.get(g_id)
            lab_txt = f" + Lab Cómputo: {lab}" if lab else ""
            resumen_grupos.append(f"• Grupo {g_id}: Aula {s_base} ({h_inicio} a {h_fin}){lab_txt}")

        return {
            "exito": True,
            "total_grupos": len(grupos),
            "materias_asignadas": total_asignadas,
            "horarios_generados": total_horarios,
            "salones_utilizados": sorted(list(salones_utilizados)),
            "resumen_grupos": resumen_grupos,
            "alertas": alertas
        }
