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

import unicodedata

def normalizar_tipo(tipo):
    if not tipo:
        return 'NORMAL'
    t = ''.join(ch for ch in unicodedata.normalize('NFD', str(tipo)) if unicodedata.category(ch) != 'Mn').upper()
    if 'TEC' in t or 'COMPUT' in t:
        return 'TECNOLOGICA'
    if 'LAB' in t:
        return 'LABORATORIO'
    if 'AUD' in t:
        return 'AUDITORIO'
    return 'NORMAL'


class GeneradorPreasignacion:
    HORA_BASE = 7  # 07:00 AM es el slot 0
    MINUTOS_SLOT = 30
    TOTAL_SLOTS_DIA = 32  # 07:00 a 23:00

    DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    PAREJAS_DIAS = [
        ("Lunes", "Miércoles"),
        ("Martes", "Jueves")
    ]

    PAREJAS_SECUNDARIAS = [
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
        self.capacidades_salones = {} # salon_id -> capacidad int

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
        cur.execute("SELECT salon_id, capacidad, tipo FROM salones ORDER BY capacidad DESC, salon_id")
        seen_upper = set()
        self.capacidades_salones.clear()
        for row in cur.fetchall():
            s_id = str(row[0]).strip()
            if s_id.upper().startswith("MEDIACION_TECNOLOGICA"):
                continue
            if s_id.upper() in seen_upper:
                continue
            seen_upper.add(s_id.upper())
            cap = int(row[1] or 0)
            self.capacidades_salones[s_id] = cap
            tipo_val = row[2] if len(row) > 2 and row[2] is not None else 'Normal'
            t = normalizar_tipo(tipo_val)
            if t == 'NORMAL':
                self.salones_normales.append(s_id)
            elif t == 'TECNOLOGICA':
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

        cur.execute("SELECT grupo_id, nivel, COALESCE(cupo, 30) FROM grupos ORDER BY nivel, grupo_id")
        grupos_bd = cur.fetchall()

        resultado = []
        for g_row in grupos_bd:
            g_id = str(g_row[0])
            nivel = g_row[1] if len(g_row) > 1 and g_row[1] is not None else 1
            cupo_grupo = int(g_row[2] if len(g_row) > 2 and g_row[2] is not None else 30)
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
                    'cupo': cupo_grupo,
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
        Divide las horas en patrones simétricos ordenados estrictamente por prioridad:
        1. Prioridad máxima: Lunes-Miércoles y Martes-Jueves
        2. Sesión única intensiva en Viernes o Sábado (ej. de 8 a 12 o bloques continuos)
        3. Parejas secundarias si no hay cupo
        """
        bloques = int(round(horas_semana * 2))
        if bloques <= 0:
            bloques = 4

        estrategias = []
        mitad1 = math.ceil(bloques / 2)
        mitad2 = bloques - mitad1

        # 1. Prioridad principal: L-X y M-J
        for d1, d2 in self.PAREJAS_DIAS:
            estrategias.append([(d1, mitad1), (d2, mitad2)])
            if mitad1 != mitad2:
                estrategias.append([(d1, mitad2), (d2, mitad1)])

        # 2. Tríadas simétricas si son 6 u 8 bloques
        if bloques == 6:
            for triada in self.TRIADAS_DIAS:
                estrategias.append([(triada[0], 2), (triada[1], 2), (triada[2], 2)])
        elif bloques == 8:
            for triada in self.TRIADAS_DIAS:
                estrategias.append([(triada[0], 3), (triada[1], 3), (triada[2], 2)])

        # 3. Asignar todas las horas en una sola sesión en Viernes o Sábado (ej. 8 a 12 o bloque completo)
        if bloques <= 10:
            estrategias.append([("Viernes", bloques)])
            estrategias.append([("Sábado", bloques)])

        # 4. Parejas secundarias
        for d1, d2 in self.PAREJAS_SECUNDARIAS:
            estrategias.append([(d1, mitad1), (d2, mitad2)])
            if mitad1 != mitad2:
                estrategias.append([(d1, mitad2), (d2, mitad1)])

        # 5. Día individual entre semana si fuera indispensable
        for d in ["Lunes", "Martes", "Miércoles", "Jueves"]:
            estrategias.append([(d, bloques)])

        return estrategias

    def ejecutar(self, filtro_periodo=None, filtro_semestre=None, solo_sin_aula=False, conservar_profesores=True):
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

        # Modo: Solo grupos que aún no tienen aula asignada
        if solo_sin_aula:
            grupos_con_aula = set()
            with obtener_cursor() as ctx_a:
                if ctx_a:
                    cur_a, _ = ctx_a
                    cur_a.execute("""
                        SELECT DISTINCT a.grupo_id
                        FROM asignaciones a
                        JOIN horarios h ON a.asignacion_id = h.asignacion_id
                        WHERE h.salon_id IS NOT NULL 
                          AND h.salon_id != 'Sin aula'
                          AND (a.estado IS NULL OR a.estado != 'cancelada')
                    """ )
                    for r in cur_a.fetchall():
                        grupos_con_aula.add(str(r[0]))

            grupos_pendientes = [g for g in grupos if str(g['grupo_id']) not in grupos_con_aula]

            if not grupos_pendientes:
                return {
                    "exito": True,
                    "total_grupos": 0,
                    "materias_asignadas": 0,
                    "horarios_generados": 0,
                    "salones_utilizados": [],
                    "resumen_grupos": ["Todos los grupos registrados ya cuentan con aula y horarios preasignados."],
                    "alertas": [],
                    "mensaje": "Todos los grupos registrados ya tienen aula asignada. No se modificó ningún horario ni profesor existente."
                }

            tot_materias = 0
            tot_horarios = 0
            salones_usados = set()
            resumen_res = []
            alertas_res = []

            for g_item in grupos_pendientes:
                gid = g_item['grupo_id']
                res_g = self.preasignar_grupo(gid)
                if res_g.get("exito"):
                    m_asig = res_g.get("materias_asignadas", 0)
                    tot_materias += m_asig
                    tot_horarios += m_asig * 2
                    s_base = res_g.get("salon_base")
                    if s_base:
                        salones_usados.add(s_base)
                    resumen_res.append(f"• Grupo {gid}: Aula {s_base} ({m_asig} materias)")
                else:
                    alertas_res.append(f"Grupo {gid}: {res_g.get('mensaje')}")

            return {
                "exito": True,
                "total_grupos": len(grupos_pendientes),
                "materias_asignadas": tot_materias,
                "horarios_generados": tot_horarios,
                "salones_utilizados": sorted(list(salones_usados)),
                "resumen_grupos": resumen_res,
                "alertas": alertas_res,
                "mensaje": f"Se preasignaron exitosamente {len(grupos_pendientes)} grupo(s) pendiente(s) ({tot_materias} materias). Los grupos con aula previa no fueron modificados."
            }

        # Separar grupos regulares (> 4 materias) y grupos reducidos (<= 4 materias)
        grupos_regulares = [g for g in grupos if len(g['materias']) > 4]
        grupos_reducidos = [g for g in grupos if len(g['materias']) <= 4]

        # Planificación de distribución en salones normales:
        # Cada salón normal puede albergar:
        # 1) 2 grupos regulares (> 4 materias: Franja 1: 07:00-13:00, Franja 2: 13:00-17:00)
        # 2) 1 grupo regular + hasta 2 grupos reducidos (07:00-13:00 regular, 13:00-15:00 red1, 15:00-17:00 red2)
        # 3) hasta 4 grupos reducidos (<= 4 materias: 07:00-09:30, 09:30-12:00, 12:00-14:30, 14:30-17:00)
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
                # Franja vespertina: slot 12 (13:00) a 20 (17:00)
                asignacion_aulas[g_tarde['grupo_id']] = (salon_asignado, 12, 20)
                i += 2
            else:
                # Quedó un grupo regular solo en este salón; si hay reducidos, empaquetar hasta 2 aquí
                if len(grupos_reducidos) >= 2:
                    g_red1 = grupos_reducidos.pop(0)
                    g_red2 = grupos_reducidos.pop(0)
                    asignacion_aulas[g_red1['grupo_id']] = (salon_asignado, 12, 16)
                    asignacion_aulas[g_red2['grupo_id']] = (salon_asignado, 16, 20)
                elif len(grupos_reducidos) == 1:
                    g_red = grupos_reducidos.pop(0)
                    asignacion_aulas[g_red['grupo_id']] = (salon_asignado, 12, 20)
                i += 1

            idx_salon += 1

        # 2. Empaquetar grupos reducidos restantes (hasta 4 por salón)
        while grupos_reducidos:
            salon_asignado = self.salones_normales[idx_salon % total_salones_norm]
            idx_salon += 1

            # Tomar hasta 4 grupos reducidos
            lote_red = []
            for _ in range(min(4, len(grupos_reducidos))):
                lote_red.append(grupos_reducidos.pop(0))

            if len(lote_red) == 4:
                # 4 grupos en el salón: 07:00-09:30 (0 a 5), 09:30-12:00 (5 a 10), 12:00-14:30 (10 a 15), 14:30-17:00 (15 a 20)
                asignacion_aulas[lote_red[0]['grupo_id']] = (salon_asignado, 0, 5)
                asignacion_aulas[lote_red[1]['grupo_id']] = (salon_asignado, 5, 10)
                asignacion_aulas[lote_red[2]['grupo_id']] = (salon_asignado, 10, 15)
                asignacion_aulas[lote_red[3]['grupo_id']] = (salon_asignado, 15, 20)
            elif len(lote_red) == 3:
                # 3 grupos en el salón: 07:00-10:20 (0 a 7), 10:20-13:40 (7 a 14), 13:40-17:00 (14 a 20)
                asignacion_aulas[lote_red[0]['grupo_id']] = (salon_asignado, 0, 7)
                asignacion_aulas[lote_red[1]['grupo_id']] = (salon_asignado, 7, 14)
                asignacion_aulas[lote_red[2]['grupo_id']] = (salon_asignado, 14, 20)
            elif len(lote_red) == 2:
                # 2 grupos en el salón: 07:00-12:00 (0 a 10) y 12:00-17:00 (10 a 20)
                asignacion_aulas[lote_red[0]['grupo_id']] = (salon_asignado, 0, 10)
                asignacion_aulas[lote_red[1]['grupo_id']] = (salon_asignado, 10, 20)
            elif len(lote_red) == 1:
                asignacion_aulas[lote_red[0]['grupo_id']] = (salon_asignado, 0, 16)

        # 3. Asignar laboratorios de cómputo fijos por grupo (Regla 2: no dispersión)
        # Cada grupo que requiera cómputo tendrá UN único salón de cómputo asignado
        laboratorio_por_grupo = {}
        if self.salones_computo:
            idx_lab = 0
            for g in grupos:
                tiene_computo = any(normalizar_tipo(m['tipo']) == 'TECNOLOGICA' for m in g['materias'])
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
                t_m = normalizar_tipo(m_tipo)
                if t_m == 'TECNOLOGICA':
                    salon_objetivo = lab_grupo or (self.salones_computo[0] if self.salones_computo else salon_base)
                elif t_m == 'AUDITORIO' and self.salones_otros.get('AUDITORIO'):
                    salon_objetivo = self.salones_otros['AUDITORIO'][0]
                elif t_m == 'LABORATORIO' and self.salones_otros.get('LABORATORIO'):
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
                        "SELECT asignacion_id, profesor_id, estado FROM asignaciones WHERE grupo_id = %s AND materia_id = %s",
                        (g_id, m_id)
                    )
                    existente = cur.fetchone()
                    if existente:
                        asig_id = existente[0]
                        p_actual = existente[1]
                        est_actual = existente[2]

                        # Si ya tenía profesor y conservar_profesores es True, mantenerlo
                        if conservar_profesores and p_actual and str(p_actual).strip() != 'SIN_ASIGNAR':
                            prof_final = p_actual
                            est_final = est_actual or 'asignado'
                        else:
                            prof_final = 'SIN_ASIGNAR'
                            est_final = 'no asignado'

                        # Limpiar horarios previos
                        cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                        cur.execute("""
                            UPDATE asignaciones
                            SET profesor_id = %s, periodo = %s, hora_inicio = %s,
                                hora_fin = %s, dias = %s, modalidad = 'Presencial', estado = %s
                            WHERE asignacion_id = %s
                        """, (prof_final, asig['periodo'], asig['hora_inicio'], asig['hora_fin'], asig['dias'], est_final, asig_id))
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

    def cargar_ocupacion_existente(self, excluir_grupo_id=None, excluir_asignaciones_ids=None):
        self.ocupacion_salones.clear()
        self.ocupacion_grupos.clear()
        excluir_asigs = set(excluir_asignaciones_ids or [])
        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            cur.execute("""
                SELECT h.salon_id, a.grupo_id, h.dia, h.hora_inicio, h.hora_fin, a.asignacion_id
                FROM horarios h
                JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                WHERE (a.estado IS NULL OR a.estado != 'cancelada')
            """)
            for s_id, g_id, dia, hi, hf, asig_id in cur.fetchall():
                if excluir_grupo_id and str(g_id) == str(excluir_grupo_id):
                    if not excluir_asigs or asig_id in excluir_asigs:
                        continue  # Se excluye porque se va a volver a acomodar
                slot_i = self.hora_a_slot(hi)
                slot_f = self.hora_a_slot(hf)
                dur = max(1, slot_f - slot_i)
                self._registrar_bloque(s_id, g_id, dia, slot_i, dur)

    def preasignar_grupo(self, grupo_id, salon_fijo=None):
        """
        Preasigna un grupo individual registrado en `grupos` y `grupo_materias`.
        Asigna salón base (tipo Normal), laboratorio de cómputo si aplica, y horarios simétricos.
        Crea las filas en `asignaciones` con profesor 'SIN_ASIGNAR' y estado 'no asignado',
        y sus sesiones correspondientes en `horarios`.
        """
        self._asegurar_profesor_sin_asignar()
        self.cargar_salones()

        if not self.salones_normales:
            return {"exito": False, "mensaje": "No hay salones de tipo Normal registrados en el sistema."}

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "No se pudo conectar a la base de datos."}
            cur, conn = ctx

            # 1. Obtener nivel y cupo del grupo
            cur.execute("SELECT nivel, COALESCE(cupo, 30) FROM grupos WHERE grupo_id = %s", (grupo_id,))
            g_row = cur.fetchone()
            if not g_row:
                return {"exito": False, "mensaje": f"El grupo '{grupo_id}' no existe en la base de datos."}
            nivel_num = 1
            cupo_g = 30
            try:
                nivel_num = int(g_row[0])
                cupo_g = int(g_row[1] if len(g_row) > 1 and g_row[1] is not None else 30)
            except (ValueError, TypeError):
                pass
            periodo = 'A' if nivel_num in (2, 4, 6, 8, 10) else 'B'

            # 2. Consultar materias vinculadas en grupo_materias
            cur.execute("""
                SELECT m.materia_id, m.nombre, IFNULL(m.horas_semana, 4.0), IFNULL(m.tipo, 'Normal')
                FROM grupo_materias gm
                JOIN materias m ON gm.materia_id = m.materia_id
                WHERE gm.grupo_id = %s
                ORDER BY m.tipo, m.materia_id
            """, (grupo_id,))
            mats_raw = cur.fetchall()
            if not mats_raw:
                return {"exito": False, "mensaje": f"El grupo '{grupo_id}' no tiene materias vinculadas en 'Grupos'."}

            materias = []
            for r in mats_raw:
                materias.append({
                    'materia_id': str(r[0]),
                    'nombre': str(r[1]),
                    'horas_semana': float(r[2] or 4.0),
                    'tipo': str(r[3] or 'NORMAL').strip().upper()
                })

            # 3. Cargar ocupación actual excluyendo este grupo
            self.cargar_ocupacion_existente(excluir_grupo_id=grupo_id)

            # 4. Determinar salón base y turno
            salon_base = salon_fijo
            shift_morning = True

            if not salon_base:
                cur.execute("""
                    SELECT DISTINCT h.salon_id
                    FROM horarios h
                    JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                    WHERE a.grupo_id = %s AND h.salon_id NOT LIKE 'MEDIACION%'
                """, (grupo_id,))
                prev_salones = [r[0] for r in cur.fetchall() if r[0] in self.salones_normales]
                if prev_salones:
                    salon_base = prev_salones[0]

            if not salon_base:
                mejor_salon = None
                mejor_shift = True
                mejor_huecos = -1

                # Priorizar aulas cuya capacidad >= cupo_g
                candidatos = sorted(
                    self.salones_normales,
                    key=lambda s: (0 if self.capacidades_salones.get(s, 0) >= cupo_g else 1, -self.capacidades_salones.get(s, 0))
                )
                for s_id in candidatos:
                    ocup_manana = sum(1 for d in self.DIAS_SEMANA for slot in range(0, 12) if self.ocupacion_salones.get((s_id, d, slot)))
                    ocup_tarde = sum(1 for d in self.DIAS_SEMANA for slot in range(12, 20) if self.ocupacion_salones.get((s_id, d, slot)))

                    if ocup_manana == 0:
                        mejor_salon = s_id
                        mejor_shift = True
                        break
                    elif ocup_tarde == 0:
                        mejor_salon = s_id
                        mejor_shift = False
                        break
                    else:
                        huecos_m = (len(self.DIAS_SEMANA) * 12) - ocup_manana
                        huecos_t = (len(self.DIAS_SEMANA) * 8) - ocup_tarde
                        if huecos_m > mejor_huecos:
                            mejor_huecos = huecos_m
                            mejor_salon = s_id
                            mejor_shift = True
                        if huecos_t > mejor_huecos:
                            mejor_huecos = huecos_t
                            mejor_salon = s_id
                            mejor_shift = False

                salon_base = mejor_salon or self.salones_normales[0]
                shift_morning = mejor_shift

            lab_computo = self.salones_computo[0] if self.salones_computo else salon_base

            slot_min = 0 if shift_morning else 12
            slot_max = 12 if shift_morning else 20

            # 5. Planificar asignación horaria de cada materia
            solucion = []
            for mat in materias:
                m_id = mat['materia_id']
                m_nom = mat['nombre']
                m_tipo = mat['tipo']
                h_sem = mat['horas_semana']

                t_m = normalizar_tipo(m_tipo)
                if t_m == 'TECNOLOGICA':
                    salon_obj = lab_computo
                elif t_m == 'AUDITORIO' and self.salones_otros.get('AUDITORIO'):
                    salon_obj = self.salones_otros['AUDITORIO'][0]
                elif t_m == 'LABORATORIO' and self.salones_otros.get('LABORATORIO'):
                    salon_obj = self.salones_otros['LABORATORIO'][0]
                else:
                    salon_obj = salon_base

                estrategias = self._generar_estrategias(h_sem)
                materia_asignada = False
                sesiones_asignadas = []

                duracion_max = max(bloques for _, bloques in estrategias[0])
                for estrategia in estrategias:
                    rango_slots = list(range(slot_min, slot_max - duracion_max + 1))
                    for slot_prueba in rango_slots:
                        posible_todos = True
                        for dia, duracion in estrategia:
                            if not self._es_posible_bloque(salon_obj, grupo_id, dia, slot_prueba, duracion):
                                posible_todos = False
                                break
                        if posible_todos:
                            for dia, duracion in estrategia:
                                self._registrar_bloque(salon_obj, grupo_id, dia, slot_prueba, duracion)
                                sesiones_asignadas.append({
                                    "dia": dia,
                                    "hora_inicio": self.slot_a_hora(slot_prueba),
                                    "hora_fin": self.slot_a_hora(slot_prueba + duracion),
                                    "salon_id": salon_obj
                                })
                            materia_asignada = True
                            break
                    if materia_asignada:
                        break

                if not materia_asignada:
                    for estrategia in estrategias:
                        ses_temp = []
                        exito_temp = True
                        for dia, duracion in estrategia:
                            enc = False
                            for sp in range(0, 20 - duracion + 1):
                                if self._es_posible_bloque(salon_obj, grupo_id, dia, sp, duracion):
                                    ses_temp.append({
                                        "dia": dia,
                                        "hora_inicio": self.slot_a_hora(sp),
                                        "hora_fin": self.slot_a_hora(sp + duracion),
                                        "salon_id": salon_obj,
                                        "slot": sp,
                                        "duracion": duracion
                                    })
                                    enc = True
                                    break
                            if not enc:
                                exito_temp = False
                                break
                        if exito_temp:
                            for st in ses_temp:
                                self._registrar_bloque(st['salon_id'], grupo_id, st['dia'], st['slot'], st['duracion'])
                                sesiones_asignadas.append({
                                    "dia": st['dia'],
                                    "hora_inicio": st['hora_inicio'],
                                    "hora_fin": st['hora_fin'],
                                    "salon_id": st['salon_id']
                                })
                            materia_asignada = True
                            break

                if materia_asignada and sesiones_asignadas:
                    dias_str = ",".join(s['dia'] for s in sesiones_asignadas)
                    hi_ref = min(s['hora_inicio'] for s in sesiones_asignadas)
                    hf_ref = max(s['hora_fin'] for s in sesiones_asignadas)
                    solucion.append({
                        "materia_id": m_id,
                        "materia_nombre": m_nom,
                        "periodo": periodo,
                        "hora_inicio": hi_ref,
                        "hora_fin": hf_ref,
                        "dias": dias_str,
                        "sesiones": sesiones_asignadas
                    })

            # 6. Sincronizar y persistir en la base de datos
            try:
                # Limpiar materias obsoletas que ya no estén en grupo_materias para este grupo
                cur.execute("""
                    DELETE FROM horarios WHERE asignacion_id IN (
                        SELECT asignacion_id FROM asignaciones
                        WHERE grupo_id = %s AND materia_id NOT IN (
                            SELECT materia_id FROM grupo_materias WHERE grupo_id = %s
                        )
                    )
                """, (grupo_id, grupo_id))
                cur.execute("""
                    DELETE FROM asignaciones
                    WHERE grupo_id = %s AND materia_id NOT IN (
                        SELECT materia_id FROM grupo_materias WHERE grupo_id = %s
                    )
                """, (grupo_id, grupo_id))

                for asig in solucion:
                    m_id = asig['materia_id']
                    cur.execute(
                        "SELECT asignacion_id FROM asignaciones WHERE grupo_id = %s AND materia_id = %s",
                        (grupo_id, m_id)
                    )
                    existente = cur.fetchone()
                    if existente:
                        asig_id = existente[0]
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
                        """, (m_id, grupo_id, asig['periodo'], asig['hora_inicio'], asig['hora_fin'], asig['dias']))
                        asig_id = cur.lastrowid

                    for ses in asig['sesiones']:
                        cur.execute("""
                            INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (asig_id, ses['salon_id'], ses['dia'], ses['hora_inicio'], ses['hora_fin']))

                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                return {"exito": False, "mensaje": f"Error persistiendo la preasignación: {err}"}

            return {
                "exito": True,
                "mensaje": f"Grupo '{grupo_id}' preasignado exitosamente en aula {salon_base} ({len(solucion)} materias).",
                "salon_base": salon_base,
                "materias_asignadas": len(solucion)
            }

    def reacomodar_grupo(self, grupo_id, modo="todo", materias_ids=None):
        """
        Reasigna las materias de un grupo manteniendo su salón actual pero en otro orden.
        modo:
          - 'todo': todas las materias del grupo (incluidas las que tienen profesor)
          - 'sin_profesor': solo materias sin profesor
          - 'especificar': solo las materias contenidas en materias_ids
        """
        import random
        self._asegurar_profesor_sin_asignar()
        self.cargar_salones()

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "No se pudo conectar a la base de datos."}
            cur, conn = ctx

            # 1. Obtener todas las materias asignadas a este grupo
            cur.execute("""
                SELECT 
                    a.asignacion_id,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(m.horas_semana, 4) AS horas_semana,
                    IFNULL(m.tipo, 'Normal') AS tipo,
                    a.profesor_id,
                    a.hora_inicio,
                    a.hora_fin,
                    a.periodo,
                    GROUP_CONCAT(DISTINCT h.salon_id) AS salones
                FROM asignaciones a
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN horarios h ON a.asignacion_id = h.asignacion_id
                WHERE a.grupo_id = %s AND (a.estado IS NULL OR a.estado != 'cancelada')
                GROUP BY a.asignacion_id
            """, (grupo_id,))
            filas = cur.fetchall()

            if not filas:
                cur.execute("SELECT COUNT(*) FROM grupo_materias WHERE grupo_id = %s", (grupo_id,))
                cnt_mats = cur.fetchone()[0]
                if cnt_mats > 0:
                    return self.preasignar_grupo(grupo_id)
                return {"exito": False, "mensaje": f"El grupo '{grupo_id}' no tiene asignaciones ni materias vinculadas."}

            # 2. Identificar el salón base del grupo y su franja horaria
            salon_base = None
            lab_computo = None
            shift_morning = True

            for f in filas:
                asig_id, m_id, m_nom, h_sem, m_tipo, prof_id, hi, hf, periodo_val, salones_str = f
                if salones_str:
                    for s in salones_str.split(','):
                        s = s.strip()
                        if s and not s.upper().startswith("MEDIACION"):
                            if s in self.salones_computo:
                                lab_computo = s
                            elif s in self.salones_normales and not salon_base:
                                salon_base = s
                if hi:
                    slot_hi = self.hora_a_slot(hi)
                    if slot_hi >= 12:
                        shift_morning = False

            if not salon_base and self.salones_normales:
                salon_base = self.salones_normales[0]
            if not lab_computo and self.salones_computo:
                lab_computo = self.salones_computo[0]

            slot_min = 0 if shift_morning else 12
            slot_max = 12 if shift_morning else 20

            # 3. Filtrar cuáles asignaciones se reacomodan y cuáles se mantienen fijas
            asigs_a_reacomodar = []
            asigs_fijas = []
            ids_a_reacomodar = set()

            for f in filas:
                asig_id, m_id, m_nom, h_sem, m_tipo, prof_id, hi, hf, periodo_val, salones_str = f
                tiene_prof = bool(prof_id and str(prof_id).strip() != 'SIN_ASIGNAR')

                reacomodar = False
                if modo == "todo":
                    reacomodar = True
                elif modo == "sin_profesor":
                    reacomodar = not tiene_prof
                elif modo == "especificar":
                    reacomodar = (str(m_id) in [str(x) for x in (materias_ids or [])])

                item = {
                    "asignacion_id": asig_id,
                    "materia_id": m_id,
                    "materia_nombre": m_nom,
                    "horas_semana": float(h_sem),
                    "tipo": str(m_tipo).strip().upper(),
                    "profesor_id": prof_id,
                    "periodo": periodo_val
                }

                if reacomodar:
                    asigs_a_reacomodar.append(item)
                    ids_a_reacomodar.add(asig_id)
                else:
                    asigs_fijas.append(item)

            if not asigs_a_reacomodar:
                return {
                    "exito": False,
                    "mensaje": "No se encontraron materias que cumplan con la condición seleccionada para reacomodar."
                }

            # 4. Cargar ocupación existente excluyendo las asignaciones que se van a reacomodar
            self.cargar_ocupacion_existente(excluir_grupo_id=grupo_id, excluir_asignaciones_ids=ids_a_reacomodar)

            # 5. Reordenar las materias para buscar otra solución (randomizado / rotado)
            mejor_solucion = None
            intentos = 0
            max_intentos = 15

            while intentos < max_intentos:
                intentos += 1
                ocup_salones_backup = dict(self.ocupacion_salones)
                ocup_grupos_backup = dict(self.ocupacion_grupos)

                materias_intento = list(asigs_a_reacomodar)
                random.shuffle(materias_intento)

                solucion_actual = []
                exito_intento = True

                for mat in materias_intento:
                    m_id = mat['materia_id']
                    m_nom = mat['materia_nombre']
                    m_tipo = mat['tipo']
                    h_sem = mat['horas_semana']

                    t_m = normalizar_tipo(m_tipo)
                    if t_m == 'TECNOLOGICA':
                        salon_objetivo = lab_computo or salon_base
                    elif t_m == 'AUDITORIO' and self.salones_otros.get('AUDITORIO'):
                        salon_objetivo = self.salones_otros['AUDITORIO'][0]
                    elif t_m == 'LABORATORIO' and self.salones_otros.get('LABORATORIO'):
                        salon_objetivo = self.salones_otros['LABORATORIO'][0]
                    else:
                        salon_objetivo = salon_base

                    estrategias = self._generar_estrategias(h_sem)
                    materia_asignada = False
                    sesiones_asignadas = []

                    duracion_max = max(bloques for _, bloques in estrategias[0])
                    for estrategia in estrategias:
                        duracion_max = max(bloques for _, bloques in estrategia)
                        rango_slots = list(range(slot_min, slot_max - duracion_max + 1))
                        for slot_prueba in rango_slots:
                            posible_todos = True
                            for dia, duracion in estrategia:
                                if not self._es_posible_bloque(salon_objetivo, grupo_id, dia, slot_prueba, duracion):
                                    posible_todos = False
                                    break
                            if posible_todos:
                                for dia, duracion in estrategia:
                                    self._registrar_bloque(salon_objetivo, grupo_id, dia, slot_prueba, duracion)
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

                    if not materia_asignada:
                        for estrategia in estrategias:
                            sesiones_temp = []
                            exito_est = True
                            for dia, duracion in estrategia:
                                encontrado_dia = False
                                for slot_prueba in range(slot_min, slot_max - duracion + 1):
                                    if self._es_posible_bloque(salon_objetivo, grupo_id, dia, slot_prueba, duracion):
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
                                    self._registrar_bloque(item['salon_id'], grupo_id, item['dia'], item['slot'], item['duracion'])
                                    sesiones_asignadas.append({
                                        "dia": item['dia'],
                                        "hora_inicio": item['hora_inicio'],
                                        "hora_fin": item['hora_fin'],
                                        "salon_id": item['salon_id']
                                    })
                                materia_asignada = True
                                break

                    if materia_asignada:
                        dias_str = ",".join(s['dia'] for s in sesiones_asignadas)
                        hi_ref = min(s['hora_inicio'] for s in sesiones_asignadas)
                        hf_ref = max(s['hora_fin'] for s in sesiones_asignadas)
                        solucion_actual.append({
                            "asignacion_id": mat['asignacion_id'],
                            "materia_id": m_id,
                            "materia_nombre": m_nom,
                            "hora_inicio": hi_ref,
                            "hora_fin": hf_ref,
                            "dias": dias_str,
                            "sesiones": sesiones_asignadas
                        })
                    else:
                        exito_intento = False
                        break

                if exito_intento:
                    mejor_solucion = solucion_actual
                    break
                else:
                    self.ocupacion_salones = ocup_salones_backup
                    self.ocupacion_grupos = ocup_grupos_backup
                    if mejor_solucion is None or len(solucion_actual) > len(mejor_solucion):
                        mejor_solucion = solucion_actual

            if not mejor_solucion or len(mejor_solucion) < len(asigs_a_reacomodar):
                return {
                    "exito": False,
                    "mensaje": f"No se encontró un acomodo completo para las {len(asigs_a_reacomodar)} materias del grupo '{grupo_id}' en el salón {salon_base}."
                }

            # 6. Persistir la nueva distribución en la base de datos
            try:
                for asig in mejor_solucion:
                    asig_id = asig['asignacion_id']
                    cur.execute("""
                        UPDATE asignaciones
                        SET hora_inicio = %s, hora_fin = %s, dias = %s
                        WHERE asignacion_id = %s
                    """, (asig['hora_inicio'], asig['hora_fin'], asig['dias'], asig_id))

                    cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                    for ses in asig['sesiones']:
                        cur.execute("""
                            INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (asig_id, ses['salon_id'], ses['dia'], ses['hora_inicio'], ses['hora_fin']))

                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                return {"exito": False, "mensaje": f"Error persistiendo el reacomodo: {err}"}

            return {
                "exito": True,
                "grupo_id": grupo_id,
                "salon_base": salon_base,
                "total_reacomodadas": len(mejor_solucion),
                "total_solicitadas": len(asigs_a_reacomodar),
                "intentos": intentos
            }


def normalizar_tipo(tipo):
    if not tipo:
        return 'NORMAL'
    t = ''.join(ch for ch in unicodedata.normalize('NFD', str(tipo)) if unicodedata.category(ch) != 'Mn').upper()
    if 'TEC' in t or 'COMPUT' in t:
        return 'TECNOLOGICA'
    if 'LAB' in t:
        return 'LABORATORIO'
    if 'AUD' in t:
        return 'AUDITORIO'
    return 'NORMAL'


