import datetime
import math
import unicodedata
import math

class GeneradorHorarios:
    MAPA_NUM_A_DIA = {
        "0": "Lunes", "1": "Martes", "2": "Miércoles", "3": "Jueves", "4": "Viernes", "5": "Sábado", "6": "Domingo",
        0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"
    }

    @staticmethod
    def _normalizar_dia(valor):
        if valor is None:
            return ""
        v_str = str(valor).strip()
        if v_str in GeneradorHorarios.MAPA_NUM_A_DIA:
            return GeneradorHorarios.MAPA_NUM_A_DIA[v_str]
        s = unicodedata.normalize('NFKD', v_str).encode('ascii', 'ignore').decode('ascii').strip().lower()
        mapa = {
            "lunes": "Lunes", "martes": "Martes", "miercoles": "Miércoles",
            "jueves": "Jueves", "viernes": "Viernes", "sabado": "Sábado", "domingo": "Domingo"
        }
        return mapa.get(s, v_str)
    def __init__(self, conexion):
        self.conexion = conexion
        self.cursor = self.conexion.cursor(dictionary=True)

        self.HORA_INICIO_CLASES = 7
        self.MINUTOS_BLOQUE = 30
        self.SLOTS_DIARIOS = 32

        self.ocupacion_salones = {}
        self.ocupacion_profesores = {}
        self.ocupacion_grupos = {}
        self.dias_activos_profesor = {}
        self.uso_salones = {}
        self.tipos_salones = {}
        self.capacidades_salones = {}

        self.separacion_online_activa = True

    def _limpiar_matrices(self):
        self.ocupacion_salones = {}
        self.ocupacion_profesores = {}
        self.ocupacion_grupos = {}
        self.dias_activos_profesor = {}
        self.uso_salones = {salon: 0 for salon in self.salones}

    def _determinar_turno_grupo(self, grupo_id, asignacion=None):
        """
        Determina si un grupo pertenece a 'Matutino' (7:00-13:00) o 'Vespertino' (13:00-17:00).
        """
        if asignacion and asignacion.get('hora_inicio'):
            slot_h = self._hora_a_slot(asignacion['hora_inicio'])
            if slot_h >= 12:
                return "Vespertino"
            else:
                return "Matutino"

        if hasattr(self, 'asignaciones'):
            for asig in self.asignaciones:
                if asig.get('grupo_id') == grupo_id and asig.get('hora_inicio'):
                    slot_h = self._hora_a_slot(asig['hora_inicio'])
                    if slot_h >= 12:
                        return "Vespertino"
                    else:
                        return "Matutino"

        for (dia, g, slot) in self.ocupacion_grupos.keys():
            if g == grupo_id:
                if slot >= 12:
                    return "Vespertino"
                else:
                    return "Matutino"

        if hasattr(self, 'asignaciones'):
            mats_grupo = [a for a in self.asignaciones if a.get('grupo_id') == grupo_id]
            if len(mats_grupo) > 4:
                return "Matutino"

        return "Vespertino"

    def _rango_slots_permitidos(self, turno, dia):
        """
        Retorna (slot_min, slot_max) permitidos para un turno y día específicos.
        Slot 0 = 07:00, Slot 12 = 13:00, Slot 20 = 17:00 (Tope estricto vespertino).
        En Viernes y Sábado, los grupos vespertinos pueden usar la mañana (07:00 a 13:00).
        """
        if dia in ("Lunes", "Martes", "Miércoles", "Jueves"):
            if turno == "Matutino":
                return 0, 12   # 07:00 a 13:00
            else:
                return 12, 20  # 13:00 a 17:00 (Tope límite a las 5:00 PM)
        else:
            # Viernes y Sábado
            if turno == "Matutino":
                return 0, 12   # 07:00 a 13:00
            else:
                # Vespertino en fin de semana: se permite desde la mañana (07:00) hasta las 17:00
                return 0, 20

    def _hora_a_slot(self, hora_time):
        if isinstance(hora_time, datetime.timedelta):
            total_minutos = hora_time.seconds // 60
            horas = total_minutos // 60
            minutos = total_minutos % 60
        elif isinstance(hora_time, datetime.time):
            horas = hora_time.hour
            minutos = hora_time.minute
        else:
            try:
                horas = hora_time.hour
                minutos = hora_time.minute
            except AttributeError:
                return 0

        slot = (horas - self.HORA_INICIO_CLASES) * 2
        if minutos >= 30:
            slot += 1
        return int(slot)

    def _slot_a_hora(self, slot):
        minutos_total = slot * 30
        horas = self.HORA_INICIO_CLASES + (minutos_total // 60)
        minutos = minutos_total % 60
        return f"{horas:02d}:{minutos:02d}:00"

    def cargar_datos(self, modo="completo"):
        filtro_estado = "WHERE a.estado != 'asignado' OR a.estado IS NULL" if modo == "parcial" else ""

        sql_asignaciones = f"""
            SELECT a.asignacion_id, a.profesor_id, a.materia_id, a.grupo_id,
                   a.hora_inicio, a.hora_fin, a.dias, a.periodo,
                   IFNULL(p.nombre, 'Sin profesor') as profesor_nombre,
                   p.en_linea,
                   IFNULL(p.acude_toda_semana, 'SI') as acude_toda_semana,
                   a.modalidad,
                   m.nombre as materia_nombre,
                   IFNULL(m.horas_semana, 4) as horas_semana,
                   IFNULL(m.tipo, 'Normal') as tipo_materia,
                   IFNULL(m.semestre_id, 99) as semestre_id,
                   IFNULL(g.cupo, 30) as cupo_grupo
            FROM asignaciones a
            LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
            JOIN materias m ON a.materia_id = m.materia_id
            LEFT JOIN grupos g ON a.grupo_id = g.grupo_id
            {filtro_estado}
        """
        self.cursor.execute(sql_asignaciones)
        self.asignaciones = self.cursor.fetchall()

        sql_disp = """
            SELECT profesor_id, dia, hora_inicio, hora_fin
            FROM profesor_disponibilidad
            ORDER BY profesor_id, id
        """
        self.cursor.execute(sql_disp)
        filas_disp = self.cursor.fetchall()

        disp_por_profesor = {}
        for f in filas_disp:
            pid = f['profesor_id']
            if pid not in disp_por_profesor:
                disp_por_profesor[pid] = []
            dia_norm = self._normalizar_dia(f['dia'])
            disp_por_profesor[pid].append({
                'dia': dia_norm,
                'hora_inicio': f['hora_inicio'],
                'hora_fin': f['hora_fin']
            })

        for asig in self.asignaciones:
            asig['disponibilidad'] = disp_por_profesor.get(asig['profesor_id'], [])

        self.cursor.execute("SELECT salon_id, capacidad, tipo FROM salones")
        salones_bd = self.cursor.fetchall()
        self.salones = [row['salon_id'] for row in salones_bd]
        self.tipos_salones = {row['salon_id']: normalizar_tipo(row['tipo']) for row in salones_bd}
        self.capacidades_salones = {row['salon_id']: int(row.get('capacidad') or 0) for row in salones_bd}

        # Auto-crear salones MEDIACION_TECNOLOGICA si hacen falta
        online_count = sum(
            1 for a in self.asignaciones
            if str(a.get('en_linea', 'NO')).upper() in ['SI', 'SÍ']
            or str(a.get('modalidad', 'Presencial')) == 'Mediacion Tecnologica'
        )
        mt_salones = [s for s in self.salones if s.upper().startswith("MEDIACION_TECNOLOGICA")]
        while len(mt_salones) < online_count:
            idx = len(mt_salones) + 1
            nuevo_id = f"MEDIACION_TECNOLOGICA_{idx}"
            try:
                self.cursor.execute("INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, 999, 'Normal')", (nuevo_id,))
                self.salones.append(nuevo_id)
                self.tipos_salones[nuevo_id] = 'Normal'
                mt_salones.append(nuevo_id)
            except Exception:
                idx += 1
                continue

    def _cargar_horarios_existentes(self):
        sql = """
            SELECT h.salon_id, h.dia, h.hora_inicio, h.hora_fin,
                   a.profesor_id, a.grupo_id
            FROM horarios h
            JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
            LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
            WHERE a.estado = 'asignado'
        """
        self.cursor.execute(sql)
        horarios_existentes = self.cursor.fetchall()

        for h in horarios_existentes:
            dia = self._normalizar_dia(h['dia'])
            salon_id = h['salon_id']
            prof_id = h['profesor_id']
            grupo_id = h['grupo_id']
            tiene_prof = prof_id and str(prof_id).strip().upper() not in ('SIN_ASIGNAR', '0000', '', 'NONE')

            slot_inicio = self._hora_a_slot(h['hora_inicio'])
            slot_fin = self._hora_a_slot(h['hora_fin'])
            duracion = slot_fin - slot_inicio

            for i in range(duracion):
                slot_actual = slot_inicio + i
                self.ocupacion_salones[(dia, salon_id, slot_actual)] = True
                if tiene_prof:
                    self.ocupacion_profesores[(dia, prof_id, slot_actual)] = True
                self.ocupacion_grupos[(dia, grupo_id, slot_actual)] = True

            if tiene_prof:
                self.dias_activos_profesor.setdefault(prof_id, set()).add(dia)

            self.uso_salones[salon_id] = self.uso_salones.get(salon_id, 0) + duracion

    def es_posible_asignar(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion.get('profesor_id')
        grupo_id = asignacion.get('grupo_id')
        modalidad = str(asignacion.get('modalidad', 'Presencial'))
        es_en_linea = str(asignacion.get('en_linea', 'NO')).upper() in ['SI', 'SÍ'] or modalidad == 'Mediacion Tecnologica'

        if slot_inicio + duracion_bloques > self.SLOTS_DIARIOS:
            return False

        # Validación estricta de turno (Matutino vs Vespertino) y tope de las 5:00 PM
        turno = self._determinar_turno_grupo(grupo_id, asignacion)
        slot_min, slot_max = self._rango_slots_permitidos(turno, dia)
        if slot_inicio < slot_min or (slot_inicio + duracion_bloques) > slot_max:
            return False

        # Si el profesor es SIN_ASIGNAR o no tiene disponibilidad definida,
        # asigna el grupo al salón sin bloquear por profesor (comportamiento tipo preasignación)
        disponibilidad = asignacion.get('disponibilidad', [])
        tiene_profesor = prof_id and str(prof_id).strip().upper() not in ('SIN_ASIGNAR', '0000', '', 'NONE')

        if tiene_profesor and disponibilidad:
            periodo_valido = None
            for p in disponibilidad:
                if self._normalizar_dia(p['dia']) == dia:
                    inicio_profe = self._hora_a_slot(p['hora_inicio'])
                    fin_profe = self._hora_a_slot(p['hora_fin'])
                    if slot_inicio >= inicio_profe and (slot_inicio + duracion_bloques) <= fin_profe:
                        periodo_valido = p
                        break

            if periodo_valido is None:
                return False

        if es_en_linea and self.separacion_online_activa and tiene_profesor:
            base_prof_id = prof_id.replace('-L', '').replace('-l', '')
            max_slot_presencial = -1

            for (d, p, s) in self.ocupacion_profesores.keys():
                if d == dia and p == base_prof_id:
                    if s > max_slot_presencial:
                        max_slot_presencial = s

            if max_slot_presencial != -1:
                if slot_inicio < (max_slot_presencial + 5):
                    return False

        for i in range(duracion_bloques):
            slot_actual = slot_inicio + i
            if self.ocupacion_salones.get((dia, salon_id, slot_actual)):
                return False
            if tiene_profesor and self.ocupacion_profesores.get((dia, prof_id, slot_actual)):
                return False
            if self.ocupacion_grupos.get((dia, grupo_id, slot_actual)):
                return False

        return True

    def registrar_ocupacion(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion.get('profesor_id')
        grupo_id = asignacion.get('grupo_id')
        tiene_profesor = prof_id and str(prof_id).strip().upper() not in ('SIN_ASIGNAR', '0000', '', 'NONE')

        for i in range(duracion_bloques):
            slot = slot_inicio + i
            self.ocupacion_salones[(dia, salon_id, slot)] = True
            if tiene_profesor:
                self.ocupacion_profesores[(dia, prof_id, slot)] = True
            self.ocupacion_grupos[(dia, grupo_id, slot)] = True

        if tiene_profesor:
            self.dias_activos_profesor.setdefault(prof_id, set()).add(dia)

        self.uso_salones[salon_id] = self.uso_salones.get(salon_id, 0) + duracion_bloques

    def _evaluar_slot(self, grupo_id, dia, slot_inicio, duracion_bloques, prof_id=None, turno="Matutino"):
        score = 0

        # 1. Compactación para el grupo (materias continuas sin huecos muertos)
        ocupados_grupo = [slot for (d, g, slot) in self.ocupacion_grupos.keys() if d == dia and g == grupo_id]
        if not ocupados_grupo:
            if dia in ("Lunes", "Martes", "Miércoles", "Jueves"):
                slot_deseado = 0 if turno == "Matutino" else 12
            else:
                slot_deseado = 0  # En viernes/sábado preferir temprano para ambos turnos
            score += 100 - abs(slot_inicio - slot_deseado) * 5
        else:
            nuevo_rango = set(range(slot_inicio, slot_inicio + duracion_bloques))
            min_dist = min(abs(n - o) for n in nuevo_rango for o in ocupados_grupo)
            distancia_real = min_dist - 1
            if distancia_real == 0:
                score += 300  # Clases consecutivas para el grupo
            elif distancia_real == 1:
                score += 150
            else:
                score -= (distancia_real * 40)

        # 2. Compactación para el profesor y control de fatiga docente (máx 4 horas continuas)
        tiene_prof = prof_id and str(prof_id).strip().upper() not in ('SIN_ASIGNAR', '0000', '', 'NONE')
        if tiene_prof:
            dias_del_profe = self.dias_activos_profesor.get(prof_id, set())
            ocupados_profe = [slot for (d, p, slot) in self.ocupacion_profesores.keys() if d == dia and p == prof_id]
            nuevo_rango = set(range(slot_inicio, slot_inicio + duracion_bloques))
            todos_slots_dia = sorted(set(ocupados_profe).union(nuevo_rango))

            # Evaluar racha máxima continua de slots del docente en este día
            max_racha = 0
            racha_actual = 0
            prev_s = None
            for s in todos_slots_dia:
                if prev_s is not None and s == prev_s + 1:
                    racha_actual += 1
                else:
                    racha_actual = 1
                prev_s = s
                if racha_actual > max_racha:
                    max_racha = racha_actual

            # Control de fatiga docente: penalizar si supera 8 slots (4 horas) continuas sin descanso
            if max_racha > 8:
                score -= (max_racha - 8) * 250
            elif max_racha > 6:
                score -= 40

            acude_semana = str(asignacion.get('acude_toda_semana', 'SI')).upper()

            if dia in dias_del_profe:
                score += 500  # Gran beneficio: mantiene al profesor en sus días ya activos
                if ocupados_profe:
                    min_dist_p = min(abs(n - o) for n in nuevo_rango for o in ocupados_profe)
                    dist_p = min_dist_p - 1
                    if dist_p == 0 and max_racha <= 8:
                        score += 250  # Clase consecutiva dentro del límite saludable
                    elif dist_p <= 2:
                        score += 50
                    else:
                        score -= (dist_p * 30)
            else:
                if acude_semana in ('NO', 'N'):
                    # PARA PROFESORES QUE NO PUEDEN TODA LA SEMANA:
                    # Penalizar fuertemente forzarlos a un 3er, 4to o 5to día
                    if len(dias_del_profe) >= 2:
                        score -= 800  # Severa penalización por abrir un 3er día
                    elif len(dias_del_profe) >= 1:
                        score -= 100
                else:
                    # PARA PROFESORES QUE SÍ PUEDEN TODA LA SEMANA:
                    # Primordial Lunes a Jueves. Viernes solo "si no hay de otra"
                    if dia == 'Viernes':
                        score -= 150  # Penalización leve para preferir L-J primero

        # 3. Bono en fin de semana para turno Vespertino si usa la mañana desocupada
        if dia in ("Viernes", "Sábado") and turno == "Vespertino" and slot_inicio < 12:
            score += 200

        return score

    def intentar_asignar_estrategia_simetrica_mixta(self, asignacion, estrategia, salon_norm, salon_tec, horarios_generados):
        mejores_opciones = []
        grupo_id = asignacion['grupo_id']
        prof_id = asignacion.get('profesor_id')
        turno = self._determinar_turno_grupo(grupo_id, asignacion)

        # Probar slots dentro de la franja permitida
        for slot_inicio in range(self.SLOTS_DIARIOS):
            posible_todos = True
            for i, (dia, duracion_bloques) in enumerate(estrategia):
                salon_a_usar = salon_tec if (i % 2 != 0 or len(estrategia) == 1) else salon_norm
                slot_min, slot_max = self._rango_slots_permitidos(turno, dia)
                if slot_inicio < slot_min or (slot_inicio + duracion_bloques) > slot_max:
                    posible_todos = False
                    break
                if not self.es_posible_asignar(asignacion, dia, slot_inicio, duracion_bloques, salon_a_usar):
                    posible_todos = False
                    break

            if posible_todos:
                score_total = sum(
                    self._evaluar_slot(grupo_id, dia, slot_inicio, duracion_bloques, prof_id=prof_id, turno=turno)
                    for dia, duracion_bloques in estrategia
                )
                mejores_opciones.append((score_total, slot_inicio))

        if mejores_opciones:
            mejores_opciones.sort(key=lambda x: x[0], reverse=True)
            mejor_slot = mejores_opciones[0][1]

            for i, (dia, duracion_bloques) in enumerate(estrategia):
                salon_a_usar = salon_tec if (i % 2 != 0 or len(estrategia) == 1) else salon_norm
                self.registrar_ocupacion(asignacion, dia, mejor_slot, duracion_bloques, salon_a_usar)
                horario = {
                    "asignacion_id": asignacion['asignacion_id'],
                    "salon_id": salon_a_usar,
                    "dia": dia,
                    "hora_inicio": self._slot_a_hora(mejor_slot),
                    "hora_fin": self._slot_a_hora(mejor_slot + duracion_bloques)
                }
                horarios_generados.append(horario)
            return True

        return False

    def intentar_asignar_estrategia_simetrica(self, asignacion, estrategia, salon, horarios_generados):
        mejores_opciones = []
        grupo_id = asignacion['grupo_id']
        prof_id = asignacion.get('profesor_id')
        turno = self._determinar_turno_grupo(grupo_id, asignacion)

        for slot_inicio in range(self.SLOTS_DIARIOS):
            posible_todos = True
            for dia, duracion_bloques in estrategia:
                slot_min, slot_max = self._rango_slots_permitidos(turno, dia)
                if slot_inicio < slot_min or (slot_inicio + duracion_bloques) > slot_max:
                    posible_todos = False
                    break
                if not self.es_posible_asignar(asignacion, dia, slot_inicio, duracion_bloques, salon):
                    posible_todos = False
                    break

            if posible_todos:
                score_total = sum(
                    self._evaluar_slot(grupo_id, dia, slot_inicio, duracion_bloques, prof_id=prof_id, turno=turno)
                    for dia, duracion_bloques in estrategia
                )
                mejores_opciones.append((score_total, slot_inicio))

        if mejores_opciones:
            mejores_opciones.sort(key=lambda x: x[0], reverse=True)
            mejor_slot = mejores_opciones[0][1]

            for dia, duracion_bloques in estrategia:
                self.registrar_ocupacion(asignacion, dia, mejor_slot, duracion_bloques, salon)
                horario = {
                    "asignacion_id": asignacion['asignacion_id'],
                    "salon_id": salon,
                    "dia": dia,
                    "hora_inicio": self._slot_a_hora(mejor_slot),
                    "hora_fin": self._slot_a_hora(mejor_slot + duracion_bloques)
                }
                horarios_generados.append(horario)
            return True

        return False

    def intentar_asignar_bloque(self, asignacion, dia, duracion_bloques, salon, horarios_generados):
        mejores_opciones = []
        grupo_id = asignacion['grupo_id']
        prof_id = asignacion.get('profesor_id')
        turno = self._determinar_turno_grupo(grupo_id, asignacion)
        slot_min, slot_max = self._rango_slots_permitidos(turno, dia)

        for slot_inicio in range(slot_min, slot_max - duracion_bloques + 1):
            if self.es_posible_asignar(asignacion, dia, slot_inicio, duracion_bloques, salon):
                score = self._evaluar_slot(grupo_id, dia, slot_inicio, duracion_bloques, prof_id=prof_id, turno=turno)
                mejores_opciones.append((score, slot_inicio))

        if mejores_opciones:
            mejores_opciones.sort(key=lambda x: x[0], reverse=True)
            mejor_slot = mejores_opciones[0][1]

            self.registrar_ocupacion(asignacion, dia, mejor_slot, duracion_bloques, salon)
            horario = {
                "asignacion_id": asignacion['asignacion_id'],
                "salon_id": salon,
                "dia": dia,
                "hora_inicio": self._slot_a_hora(mejor_slot),
                "hora_fin": self._slot_a_hora(mejor_slot + duracion_bloques)
            }
            horarios_generados.append(horario)
            return True

        return False

    def _generar_estrategias_ordenadas(self, asignacion, bloques_totales):
        """
        Genera estrategias de distribución de días considerando la disponibilidad semanal del docente:
        - Para acude_toda_semana == 'NO':
          Compacta en 2 días: Prioridad L-X, M-J, y parejas con Viernes (L-V, M-V, X-V, J-V).
        - Para acude_toda_semana == 'SI':
          Primordial: Lunes a Jueves (L-X, M-J, L-J, M-X, multidia L-J).
          Secundario ('Si no hay de otra'): Incluye combinaciones con Viernes (L-V, M-V, X-V, J-V, V).
        """
        prof_id = asignacion.get('profesor_id')
        tiene_prof = prof_id and str(prof_id).strip().upper() not in ('SIN_ASIGNAR', '0000', '', 'NONE')
        dias_profe = self.dias_activos_profesor.get(prof_id, set()) if tiene_prof else set()
        acude_semana = str(asignacion.get('acude_toda_semana', 'SI')).upper()

        b_mitad1 = math.ceil(bloques_totales / 2)
        b_mitad2 = bloques_totales - b_mitad1
        b_mayor = 4 if bloques_totales == 6 else b_mitad1
        b_menor = 2 if bloques_totales == 6 else b_mitad2

        # Parejas Lunes - Miércoles
        estrategias_lx = [
            [("Lunes", b_mitad1), ("Miércoles", b_mitad2)],
            [("Lunes", b_mayor), ("Miércoles", b_menor)],
            [("Lunes", b_menor), ("Miércoles", b_mayor)],
            [("Lunes", bloques_totales)],
            [("Miércoles", bloques_totales)]
        ]

        # Parejas Martes - Jueves
        estrategias_mj = [
            [("Martes", b_mitad1), ("Jueves", b_mitad2)],
            [("Martes", b_mayor), ("Jueves", b_menor)],
            [("Martes", b_menor), ("Jueves", b_mayor)],
            [("Martes", bloques_totales)],
            [("Jueves", bloques_totales)]
        ]

        # Parejas compactas con Viernes (2 días)
        estrategias_parejas_viernes = [
            [("Lunes", b_mitad1), ("Viernes", b_mitad2)],
            [("Martes", b_mitad1), ("Viernes", b_mitad2)],
            [("Miércoles", b_mitad1), ("Viernes", b_mitad2)],
            [("Jueves", b_mitad1), ("Viernes", b_mitad2)],
            [("Viernes", bloques_totales)]
        ]

        # Desborde con Sábado
        estrategias_sabado = [
            [("Viernes", b_mitad1), ("Sábado", b_mitad2)],
            [("Jueves", b_mitad1), ("Sábado", b_mitad2)],
            [("Sábado", bloques_totales)]
        ]

        if bloques_totales == 8:
            estrategias_lx.insert(0, [("Lunes", 4), ("Miércoles", 4)])
            estrategias_mj.insert(0, [("Martes", 4), ("Jueves", 4)])
            estrategias_parejas_viernes.extend([
                [("Lunes", 4), ("Viernes", 4)],
                [("Martes", 4), ("Viernes", 4)],
                [("Miércoles", 4), ("Viernes", 4)],
                [("Jueves", 4), ("Viernes", 4)]
            ])

        if acude_semana in ('NO', 'N'):
            # DOCENTE QUE NO PUEDE TODA LA SEMANA:
            # Concentrar rígidamente en 2 días.
            # Si ya tiene días activos, priorizar el par que corresponda
            if any(d in dias_profe for d in ("Martes", "Jueves")) and not any(d in dias_profe for d in ("Lunes", "Miércoles")):
                return estrategias_mj + estrategias_lx + estrategias_parejas_viernes + estrategias_sabado
            elif any(d in dias_profe for d in ("Viernes",)) and not any(d in dias_profe for d in ("Lunes", "Martes", "Miércoles", "Jueves")):
                return estrategias_parejas_viernes + estrategias_lx + estrategias_mj + estrategias_sabado
            else:
                return estrategias_lx + estrategias_mj + estrategias_parejas_viernes + estrategias_sabado

        else:
            # DOCENTE QUE SÍ PUEDE TODA LA SEMANA:
            # Primordial: Lunes a Jueves (L-X, M-J, L-J, M-X, multidia L-J)
            # Secundario ("si no hay de otra"): Combinaciones con Viernes
            estrategias_lj_alternas = [
                [("Lunes", b_mitad1), ("Jueves", b_mitad2)],
                [("Martes", b_mitad1), ("Miércoles", b_mitad2)]
            ]
            estrategias_multidia_lj = []
            if bloques_totales == 8:
                estrategias_multidia_lj.append([("Lunes", 2), ("Martes", 2), ("Miércoles", 2), ("Jueves", 2)])
            elif bloques_totales == 6:
                estrategias_multidia_lj.append([("Lunes", 2), ("Martes", 2), ("Miércoles", 2)])
                estrategias_multidia_lj.append([("Martes", 2), ("Miércoles", 2), ("Jueves", 2)])

            tier_primordial_lj = estrategias_lx + estrategias_mj + estrategias_lj_alternas + estrategias_multidia_lj
            tier_secundario_viernes = estrategias_parejas_viernes + estrategias_sabado

            if any(d in dias_profe for d in ("Martes", "Jueves")) and not any(d in dias_profe for d in ("Lunes", "Miércoles")):
                tier_primordial_lj = estrategias_mj + estrategias_lx + estrategias_lj_alternas + estrategias_multidia_lj

            return tier_primordial_lj + tier_secundario_viernes

    def _calcular_horas_disponibles(self, asignacion):
        disponibilidad = asignacion.get('disponibilidad', [])
        if not disponibilidad:
            return 0, 0, []

        total_slots = 0
        periodos = []
        dias_unicos = set()
        for p in disponibilidad:
            s_ini = self._hora_a_slot(p['hora_inicio'])
            s_fin = self._hora_a_slot(p['hora_fin'])
            if s_fin > s_ini:
                total_slots += (s_fin - s_ini)
            periodos.append({'dia': p['dia'], 'slot_inicio': s_ini, 'slot_fin': s_fin})
            dias_unicos.add(p['dia'])

        return total_slots / 2, len(dias_unicos), periodos

    def ejecutar(self, modo="completo"):
        self.cargar_datos(modo)
        self._limpiar_matrices()

        if modo == "parcial":
            self._cargar_horarios_existentes()

        horarios_generados = []
        alertas_generadas = []
        _batch_map = {}

        self.asignaciones.sort(
            key=lambda x: (
                1 if str(x.get('en_linea', 'NO')).upper() in ['SI', 'SÍ'] or str(x.get('modalidad', 'Presencial')) == 'Mediacion Tecnologica' else 0,
                0 if normalizar_tipo(x.get('tipo_materia')) in ('TECNOLOGICA', 'LABORATORIO', 'AUDITORIO') else 1,
                int(x.get('semestre_id', 99)),
                str(x.get('profesor_id', 'ZZZ')),
                -float(x.get('horas_semana', 0))
            )
        )

        for asignacion in self.asignaciones:
            horas_totales = float(asignacion['horas_semana'])
            bloques_totales = int(horas_totales * 2)
            tipo_materia = asignacion.get('tipo_materia', 'Normal').lower()
            es_en_linea = str(asignacion.get('en_linea', 'NO')).upper() in ['SI', 'SÍ'] or str(asignacion.get('modalidad', 'Presencial')) == 'Mediacion Tecnologica'

            estrategias = self._generar_estrategias_ordenadas(asignacion, bloques_totales)

            asignado_completamente = False
            gen_prev = len(horarios_generados)

            def _intentar_batch(antes=True, despues=True):
                nonlocal asignado_completamente
                bkey = (asignacion['profesor_id'], asignacion['materia_id'])
                if bkey not in _batch_map:
                    return
                for ref in list(_batch_map[bkey]):
                    salon_id = ref['salon_id']
                    dia = ref['dia']
                    h_ini = self._hora_a_slot(datetime.datetime.strptime(ref['hora_inicio'], "%H:%M:%S").time())
                    h_fin = self._hora_a_slot(datetime.datetime.strptime(ref['hora_fin'], "%H:%M:%S").time())
                    for slot_propuesto, lado in [(h_ini - bloques_totales, "ANTES"), (h_fin, "DESPUÉS")]:
                        if lado == "ANTES" and (not antes or slot_propuesto < 0):
                            continue
                        if lado == "DESPUÉS" and (not despues or slot_propuesto + bloques_totales > self.SLOTS_DIARIOS):
                            continue
                        if self.es_posible_asignar(asignacion, dia, slot_propuesto, bloques_totales, salon_id):
                            self.registrar_ocupacion(asignacion, dia, slot_propuesto, bloques_totales, salon_id)
                            horario = {
                                "asignacion_id": asignacion['asignacion_id'],
                                "salon_id": salon_id,
                                "dia": dia,
                                "hora_inicio": self._slot_a_hora(slot_propuesto),
                                "hora_fin": self._slot_a_hora(slot_propuesto + bloques_totales)
                            }
                            horarios_generados.append(horario)
                            _batch_map[bkey].append(horario)
                            asignado_completamente = True
                            print(f"[BATCH] {asignacion.get('materia_nombre','?')} ({asignacion['grupo_id']}) colocado {lado} de {ref['hora_inicio']}-{ref['hora_fin']} en {salon_id}")
                            return

            key = (asignacion['profesor_id'], asignacion['materia_id'])
            if key in _batch_map and not es_en_linea and tipo_materia not in ('laboratorio', 'auditorio'):
                _intentar_batch()

            if not asignado_completamente:
                # 1. Determinar salones compatibles según tipo de materia y modalidad
                tipo_norm = normalizar_tipo(tipo_materia)
                if es_en_linea:
                    salones_priorizados = sorted([s for s in self.salones if s.upper().startswith("MEDIACION_TECNOLOGICA")])
                elif tipo_norm == 'AUDITORIO':
                    salones_aud = [s for s in self.salones if self.tipos_salones.get(s, 'NORMAL') == 'AUDITORIO' and not s.upper().startswith("MEDIACION_TECNOLOGICA")]
                    salones_priorizados = sorted(salones_aud, key=lambda s: self.uso_salones.get(s, 0))
                elif tipo_norm == 'TECNOLOGICA':
                    salones_tec = [s for s in self.salones if self.tipos_salones.get(s, 'NORMAL') == 'TECNOLOGICA' and not s.upper().startswith("MEDIACION_TECNOLOGICA")]
                    salones_priorizados = sorted(salones_tec, key=lambda s: self.uso_salones.get(s, 0))
                elif tipo_norm == 'LABORATORIO':
                    salones_lab = [s for s in self.salones if self.tipos_salones.get(s, 'NORMAL') == 'LABORATORIO' and not s.upper().startswith("MEDIACION_TECNOLOGICA")]
                    salones_norm = [s for s in self.salones if self.tipos_salones.get(s, 'NORMAL') == 'NORMAL' and not s.upper().startswith("MEDIACION_TECNOLOGICA")]
                    salones_priorizados = sorted(salones_lab + salones_norm, key=lambda s: self.uso_salones.get(s, 0))
                else:
                    salones_norm = [s for s in self.salones if self.tipos_salones.get(s, 'NORMAL') == 'NORMAL' and not s.upper().startswith("MEDIACION_TECNOLOGICA")]
                    cupo_g = int(asignacion.get('cupo_grupo') or 30)
                    salones_priorizados = sorted(
                        salones_norm,
                        key=lambda s: (0 if self.capacidades_salones.get(s, 999) >= cupo_g else 1, self.uso_salones.get(s, 0))
                    )

                # Priorizar el salón que el grupo ya tenga asignado en otra materia para mantenerlo en su aula base
                if not es_en_linea and tipo_materia == 'normal':
                    for (dia, s, slot) in self.ocupacion_salones.keys():
                        if (dia, asignacion['grupo_id'], slot) in self.ocupacion_grupos:
                            if s in salones_priorizados:
                                salones_priorizados.remove(s)
                                salones_priorizados.insert(0, s)
                                break

                # 2. Intentar asignación con estrategia simétrica
                for salon in salones_priorizados:
                    if asignado_completamente:
                        break
                    for estrategia in estrategias:
                        horarios_temporales = []
                        if self.intentar_asignar_estrategia_simetrica(asignacion, estrategia, salon, horarios_temporales):
                            horarios_generados.extend(horarios_temporales)
                            asignado_completamente = True
                            break

                # 3. Fallback: Probar bloques individuales si la estrategia simétrica no cupo en el mismo slot
                if not asignado_completamente:
                    for salon in salones_priorizados:
                        if asignado_completamente:
                            break
                        for estrategia in estrategias:
                            exito_estrategia = True
                            horarios_temporales = []
                            for dia, bloques_requeridos in estrategia:
                                exito_bloque = self.intentar_asignar_bloque(asignacion, dia, bloques_requeridos, salon, horarios_temporales)
                                if not exito_bloque:
                                    exito_estrategia = False
                                    break
                            if exito_estrategia:
                                horarios_generados.extend(horarios_temporales)
                                asignado_completamente = True
                                break
                            else:
                                for ht in horarios_temporales:
                                    self._deshacer_ocupacion(asignacion, ht['dia'], self._hora_a_slot(datetime.datetime.strptime(ht['hora_inicio'], "%H:%M:%S").time()), ht['salon_id'], bloques_requeridos)
                                exito_estrategia = True
                                horarios_temporales = []
                                for dia, bloques_requeridos in estrategia:
                                    exito_bloque = self.intentar_asignar_bloque(asignacion, dia, bloques_requeridos, salon, horarios_temporales)
                                    if not exito_bloque:
                                        exito_estrategia = False
                                        break
                                if exito_estrategia:
                                    horarios_generados.extend(horarios_temporales)
                                    asignado_completamente = True
                                    break
                                else:
                                    for ht in horarios_temporales:
                                        self._deshacer_ocupacion(asignacion, ht['dia'], self._hora_a_slot(datetime.datetime.strptime(ht['hora_inicio'], "%H:%M:%S").time()), ht['salon_id'], bloques_requeridos)

                if not asignado_completamente and not es_en_linea and tipo_materia not in ('laboratorio', 'auditorio'):
                    _intentar_batch()

            if asignado_completamente:
                key = (asignacion['profesor_id'], asignacion['materia_id'])
                for h in horarios_generados[gen_prev:]:
                    _batch_map.setdefault(key, []).append(h)

            if not asignado_completamente:
                prof_id = asignacion.get('profesor_id', '?')
                grupo_id = asignacion.get('grupo_id', '?')
                mat_id = asignacion.get('materia_id', '?')
                prof_nombre = asignacion.get('profesor_nombre', prof_id)
                mat_nombre = asignacion.get('materia_nombre', mat_id)
                tipo_mat = asignacion.get('tipo_materia', 'Normal').lower()

                sugerencias = []
                causas = []

                try:
                    hrs_profesor, num_dias, periodos = self._calcular_horas_disponibles(asignacion)
                    # --- DIAGNÓSTICO EN CONSOLA ---
                    print(f"\n[DEBUG] Falló asignación: {mat_nombre} ({grupo_id}) -> profesor {prof_id} ({prof_nombre})")
                    print(f"[DEBUG]   horas_totales={horas_totales}, hrs_profesor(según BD)={hrs_profesor}, num_dias={num_dias}")
                    print(f"[DEBUG]   periodos disponibles en BD para {prof_id}:")
                    for p in periodos:
                        print(f"          - {p['dia']}: slot {p['slot_inicio']}-{p['slot_fin']}")
                    ocupadas = []
                    for (d, p, s) in sorted(self.ocupacion_profesores.keys()):
                        if p == prof_id:
                            ocupadas.append(f"{d} slot {s}")
                    if ocupadas:
                        print(f"[DEBUG]   slots ocupados para {prof_id}: {ocupadas}")
                    else:
                        print(f"[DEBUG]   slots ocupados para {prof_id}: (ninguno)")
                    # --- FIN DIAGNÓSTICO ---

                    if num_dias > 0 and hrs_profesor > 0:
                        horas_ya_asignadas = 0
                        for (d, p, s) in self.ocupacion_profesores.keys():
                            if p == prof_id:
                                horas_ya_asignadas += 0.5

                        horas_restantes = hrs_profesor - horas_ya_asignadas

                        if horas_totales > hrs_profesor:
                            causas.append(
                                f"El profesor '{prof_nombre}' solo tiene {hrs_profesor:.0f}h "
                                f"disponibles/semana por contrato, pero la materia exige {horas_totales}h.")
                            sugerencias.append(
                                f"Reducir horas de la materia '{mat_nombre}' ({mat_id}) a máximo "
                                f"{int(hrs_profesor)}h, o ampliar el horario de '{prof_nombre}'.")

                        elif horas_totales > horas_restantes:
                            causas.append(
                                f"Sobrecarga: El profesor '{prof_nombre}' ya tiene {horas_ya_asignadas:.1f}h ocupadas en otros grupos. "
                                f"Solo le quedan {horas_restantes:.1f}h libres, pero la materia pide {horas_totales}h.")
                            sugerencias.append(
                                f"Asignar la materia a otro profesor o liberarle horas a '{prof_nombre}'.")

                    if not es_en_linea and self.salones:
                        salones_compatibles = []
                        for s in self.salones:
                            if s.upper().startswith("MEDIACION_TECNOLOGICA"):
                                continue
                            t_salon = self.tipos_salones.get(s, 'NORMAL')
                            tm_norm = normalizar_tipo(tipo_mat)
                            if tm_norm == 'LABORATORIO' and t_salon in ['LABORATORIO', 'NORMAL']:
                                salones_compatibles.append(s)
                            elif tm_norm == 'TECNOLOGICA' and t_salon == 'TECNOLOGICA':
                                salones_compatibles.append(s)
                            elif tm_norm == 'AUDITORIO' and t_salon == 'AUDITORIO':
                                salones_compatibles.append(s)
                            elif tm_norm == 'NORMAL':
                                salones_compatibles.append(s)

                        if not salones_compatibles:
                            causas.append(f"No hay salones disponibles de tipo '{tipo_mat}' para esta materia.")
                            if tipo_mat == 'laboratorio':
                                sugerencias.append(f"Registrar salones tipo 'Laboratorio' o cambiar la materia a 'Normal'.")
                            elif tipo_mat in ['tecnológica', 'tecnologica', 'laboratorio de computacion', 'laboratorio de computación']:
                                sugerencias.append(f"Registrar salones tipo 'Laboratorio de computación' o cambiar la materia a 'Normal'.")
                            else:
                                sugerencias.append("Registrar más salones de tipo 'Normal'.")

                    if num_dias == 1 and horas_totales > 4:
                        causas.append(
                            f"El profesor '{prof_nombre}' solo tiene 1 día disponible, "
                            f"pero la materia necesita {horas_totales}h en bloque.")
                        sugerencias.append(
                            f"Distribuir la materia en mínimo {int(horas_totales / 4 + 1)} días, "
                            f"o agregar más días de disponibilidad.")

                except Exception:
                    pass

                if not causas:
                    if es_en_linea:
                        causas.append(
                            "No se encontró espacio en línea disponible "
                            "sin conflictos con clases presenciales.")
                        sugerencias.append("Ampliar el horario del profesor o reducir horas de la materia.")
                    else:
                        causas.append(
                            "No hay salones disponibles en los horarios compatibles "
                            f"con el profesor '{prof_nombre}' y el grupo '{grupo_id}'.")
                        sugerencias.append(
                            f"Revisar disponibilidad del profesor '{prof_nombre}', "
                            "o agregar más salones.")

                def _slot_a_hora_short(s):
                    return self._slot_a_hora(s)[:5]

                detalles_extra = []
                detalles_extra.append(f"Horas requeridas: {horas_totales}h")
                detalles_extra.append(f"Disponibilidad del profesor: {hrs_profesor:.0f}h en {num_dias} día(s)")
                if periodos:
                    for p in periodos:
                        detalles_extra.append(f"  {p['dia']}: {_slot_a_hora_short(p['slot_inicio'])}-{_slot_a_hora_short(p['slot_fin'])}")
                ocupadas = []
                for (d, p, s) in sorted(self.ocupacion_profesores.keys()):
                    if p == prof_id:
                        ocupadas.append(f"{d} {_slot_a_hora_short(s)}")
                if ocupadas:
                    detalles_extra.append(f"Horarios ya ocupados del profesor: {', '.join(ocupadas[:10])}")
                    if len(ocupadas) > 10:
                        detalles_extra.append(f"  ... y {len(ocupadas)-10} más")

                if not es_en_linea and self.salones:
                    salones_compatibles = []
                    for s in self.salones:
                        if s.upper().startswith("MEDIACION_TECNOLOGICA"):
                            continue
                        t_salon = self.tipos_salones.get(s, 'NORMAL')
                        tm_norm = normalizar_tipo(tipo_mat)
                        if tm_norm == 'AUDITORIO' and t_salon == 'AUDITORIO':
                            salones_compatibles.append(s)
                        elif tm_norm == 'LABORATORIO' and t_salon in ['LABORATORIO', 'NORMAL']:
                            salones_compatibles.append(s)
                        elif tm_norm == 'TECNOLOGICA' and t_salon == 'TECNOLOGICA':
                            salones_compatibles.append(s)
                        elif tm_norm == 'NORMAL':
                            salones_compatibles.append(s)

                    if salones_compatibles:
                        libres = []
                        for s in salones_compatibles:
                            for p in periodos:
                                for slot in range(p['slot_inicio'], p['slot_fin']):
                                    if not self.ocupacion_salones.get((p['dia'], s, slot)):
                                        libres.append(f"{s} ({p['dia']} {_slot_a_hora_short(slot)})")
                                        break
                        if libres:
                            detalles_extra.append(f"Salones compatibles con espacio libre: {', '.join(libres[:5])}")
                            if len(libres) > 5:
                                detalles_extra.append(f"  ... y {len(libres)-5} más")
                        else:
                            detalles_extra.append("Salones compatibles pero todos ocupados en los horarios del profesor.")

                alerta = {
                    "materia": mat_nombre.upper(),
                    "materia_id": mat_id,
                    "grupo": grupo_id,
                    "profesor": prof_nombre.upper(),
                    "profesor_id": prof_id,
                    "causas": causas,
                    "sugerencias": sugerencias[:3],
                    "detalles_extra": detalles_extra
                }
                alertas_generadas.append(alerta)
                causa_corta = causas[0] if causas else "sin causa identificada"
                print(f"ALERTA: No se pudo asignar {mat_nombre} ({grupo_id}) - {causa_corta}")

        self.guardar_en_bd(horarios_generados, modo)

        return len(horarios_generados), alertas_generadas

    def _deshacer_ocupacion(self, asignacion, dia, slot_inicio, salon_id, duracion_bloques):
        prof_id = asignacion.get('profesor_id')
        grupo_id = asignacion.get('grupo_id')
        tiene_profesor = prof_id and str(prof_id).strip().upper() not in ('SIN_ASIGNAR', '0000', '', 'NONE')

        for i in range(duracion_bloques):
            slot = slot_inicio + i
            if (dia, salon_id, slot) in self.ocupacion_salones:
                del self.ocupacion_salones[(dia, salon_id, slot)]
            if tiene_profesor and (dia, prof_id, slot) in self.ocupacion_profesores:
                del self.ocupacion_profesores[(dia, prof_id, slot)]
            if (dia, grupo_id, slot) in self.ocupacion_grupos:
                del self.ocupacion_grupos[(dia, grupo_id, slot)]

        self.uso_salones[salon_id] -= duracion_bloques

    def dias_disponibles_lista(self, asignacion):
        try:
            disponibilidad = asignacion.get('disponibilidad', [])
            if disponibilidad:
                dias = list(set(p['dia'] for p in disponibilidad if p.get('dia')))
                return dias
            return ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        except Exception:
            return ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    def guardar_en_bd(self, lista_horarios, modo="completo"):
        try:
            if modo == "completo":
                self.cursor.execute("DELETE FROM horarios")
                self.cursor.execute("UPDATE asignaciones SET estado = 'pendiente'")
            elif modo == "parcial" and lista_horarios:
                ids_a_limpiar = list(set([str(h['asignacion_id']) for h in lista_horarios]))
                format_clean = ','.join(['%s'] * len(ids_a_limpiar))
                self.cursor.execute(f"DELETE FROM horarios WHERE asignacion_id IN ({format_clean})", tuple(ids_a_limpiar))

            sql_insert = """INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                     VALUES (%s, %s, %s, %s, %s)"""
            valores = [(h['asignacion_id'], h['salon_id'], h['dia'], h['hora_inicio'], h['hora_fin'])
                       for h in lista_horarios]

            if valores:
                self.cursor.executemany(sql_insert, valores)

            if lista_horarios:
                ids_asignados = list(set([str(h['asignacion_id']) for h in lista_horarios]))
                format_strings = ','.join(['%s'] * len(ids_asignados))
                sql_update = f"UPDATE asignaciones SET estado = 'asignado' WHERE asignacion_id IN ({format_strings})"
                self.cursor.execute(sql_update, tuple(ids_asignados))

                # Actualizar también hora_inicio, hora_fin y dias en asignaciones para la vista previa de la UI
                horarios_por_asig = {}
                for h in lista_horarios:
                    horarios_por_asig.setdefault(h['asignacion_id'], []).append(h)

                for asig_id, lista_h in horarios_por_asig.items():
                    dias_asig = sorted(list(set(h['dia'] for h in lista_h)))
                    h_ini = min(h['hora_inicio'] for h in lista_h)
                    h_fin = max(h['hora_fin'] for h in lista_h)
                    dias_str = ', '.join(dias_asig)
                    self.cursor.execute(
                        "UPDATE asignaciones SET hora_inicio = %s, hora_fin = %s, dias = %s WHERE asignacion_id = %s",
                        (h_ini, h_fin, dias_str, asig_id)
                    )

            self.conexion.commit()
        except Exception as e:
            self.conexion.rollback()
            raise e
##6 1
#2 recursadores
#3
#4 normales, 2 con menos
#5= 4 completos 1 imconpletro 1 adicional de ingles
#7 3 completos y 1 incompleto
#9 3 completos
#añador seccion para dar de alta grupos para modificarlo y quitar la lista fija


#cambiar asignacion a mas manual

#martes ultima revision
#expo jueves 25 junio
#quitar esa parte d elos laboratoriosimport unicodedata

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


