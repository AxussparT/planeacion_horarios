import mysql.connector
import datetime
import math
import unicodedata

class GeneradorHorarios:
    MAPA_NUM_A_DIA = {"0": "Lunes", "1": "Martes", "2": "Miércoles", "3": "Jueves", "4": "Viernes", "5": "Sábado", "6": "Domingo"}

    @staticmethod
    def _normalizar_dia(valor):
        s = unicodedata.normalize('NFKD', str(valor)).encode('ascii', 'ignore').decode('ascii').strip().lower()
        mapa = {"lunes": "Lunes", "martes": "Martes", "miercoles": "Miércoles", "jueves": "Jueves", "viernes": "Viernes", "sabado": "Sábado", "domingo": "Domingo"}
        if s in mapa:
            return mapa[s]
        return GeneradorHorarios.MAPA_NUM_A_DIA.get(str(valor).strip(), str(valor).strip())

    def __init__(self, conexion):
        self.conexion = conexion
        self.cursor = self.conexion.cursor(dictionary=True)

        self.HORA_INICIO_CLASES = 7
        self.MINUTOS_BLOQUE = 30
        self.SLOTS_DIARIOS = 32

        self.ocupacion_salones = {}
        self.ocupacion_profesores = {}
        self.ocupacion_grupos = {}
        self.uso_salones = {}
        self.tipos_salones = {}

        self.separacion_online_activa = False

        self.salon_por_materia_profesor = {}

    def _limpiar_matrices(self):
        self.ocupacion_salones = {}
        self.ocupacion_profesores = {}
        self.ocupacion_grupos = {}
        self.uso_salones = {salon: 0 for salon in self.salones}
        self.salon_por_materia_profesor = {}

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
                   a.hora_inicio, a.hora_fin,
                   p.nombre as profesor_nombre,
                   a.modalidad,
                   a.dias,
                   m.nombre as materia_nombre,
                   IFNULL(m.horas_semana, 4) as horas_semana,
                   IFNULL(m.tipo, 'Normal') as tipo_materia,
                   IFNULL(m.semestre_id, 99) as semestre_id
            FROM asignaciones a
            JOIN profesores p ON a.profesor_id = p.profesor_id
            JOIN materias m ON a.materia_id = m.materia_id
            {filtro_estado}
        """
        self.cursor.execute(sql_asignaciones)
        raw_asignaciones = self.cursor.fetchall()

        self.asignaciones = []
        skipped = 0
        for a in raw_asignaciones:
            if a['hora_inicio'] is not None and a['hora_fin'] is not None:
                slot_ini = self._hora_a_slot(a['hora_inicio'])
                slot_fin = self._hora_a_slot(a['hora_fin'])
                if slot_fin > slot_ini:
                    a['slot_inicio'] = slot_ini
                    a['slot_duracion'] = slot_fin - slot_ini
                    self.asignaciones.append(a)
                else:
                    skipped += 1
                    print(f"[SKIP] {a.get('materia_nombre','?')} ({a.get('grupo_id','?')}): hora_fin ({a['hora_fin']}) <= hora_inicio ({a['hora_inicio']})")
            else:
                skipped += 1
                print(f"[SKIP] {a.get('materia_nombre','?')} ({a.get('grupo_id','?')}): hora_inicio o hora_fin es NULL")
        print(f"[MOTOR] Total asignaciones: {len(raw_asignaciones)}, procesables: {len(self.asignaciones)}, omitidas: {skipped}")

        print(f"[DEBUG MOTOR] ===== CARGANDO DISPONIBILIDAD =====")
        sql_disp = """
            SELECT profesor_id, dia, hora_inicio, hora_fin
            FROM profesor_disponibilidad
            ORDER BY profesor_id, id
        """
        self.cursor.execute(sql_disp)
        filas_disp = self.cursor.fetchall()
        print(f"[DEBUG MOTOR] Total filas disponibilidad: {len(filas_disp)}")

        disp_por_profesor = {}
        for f in filas_disp:
            pid = f['profesor_id']
            raw_dia = str(f['dia'])
            norm_dia = self._normalizar_dia(raw_dia)
            if raw_dia != norm_dia:
                print(f"[DEBUG MOTOR] CONVERSION DIA: raw='{raw_dia}' -> norm='{norm_dia}' (prof {pid})")
            if pid not in disp_por_profesor:
                disp_por_profesor[pid] = []
            disp_por_profesor[pid].append({
                'dia': norm_dia,
                'hora_inicio': f['hora_inicio'],
                'hora_fin': f['hora_fin']
            })

        for asig in self.asignaciones:
            disp = disp_por_profesor.get(asig['profesor_id'], [])
            asig['disponibilidad'] = disp
            raw_days = set(d['dia'] for d in disp)
            print(f"[DEBUG MOTOR] Asignacion {asig['materia_nombre']} ({asig['grupo_id']}) -> prof {asig['profesor_id']} -> dias disp: {raw_days}")

        self.cursor.execute("SELECT salon_id, tipo FROM salones")
        salones_bd = self.cursor.fetchall()
        self.salones = [row['salon_id'] for row in salones_bd]
        self.tipos_salones = {row['salon_id']: (row['tipo'] or 'Normal') for row in salones_bd}

        online_count = sum(
            1 for a in self.asignaciones
            if str(a.get('modalidad', 'Presencial')) == 'Mediacion Tecnologica'
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
            JOIN profesores p ON a.profesor_id = p.profesor_id
        """
        self.cursor.execute(sql)
        horarios_existentes = self.cursor.fetchall()

        for h in horarios_existentes:
            dia = h['dia']
            salon_id = h['salon_id']
            prof_id = h['profesor_id']
            grupo_id = h['grupo_id']

            slot_inicio = self._hora_a_slot(h['hora_inicio'])
            slot_fin = self._hora_a_slot(h['hora_fin'])
            duracion = slot_fin - slot_inicio

            for i in range(duracion):
                slot_actual = slot_inicio + i
                self.ocupacion_salones[(dia, salon_id, slot_actual)] = True
                self.ocupacion_profesores[(dia, prof_id, slot_actual)] = True
                self.ocupacion_grupos[(dia, grupo_id, slot_actual)] = True

            self.uso_salones[salon_id] = self.uso_salones.get(salon_id, 0) + duracion

    def _dias_disponibles_para_horario(self, asignacion):
        slot_ini = asignacion['slot_inicio']
        duracion = asignacion['slot_duracion']
        slot_fin = slot_ini + duracion

        dias_permitidos = None
        raw_dias = asignacion.get('dias')
        if raw_dias:
            dias_permitidos = {self._normalizar_dia(d.strip()) for d in raw_dias.split(',')}

        dias_validos = []
        for p in asignacion.get('disponibilidad', []):
            p_dia = p['dia']
            if dias_permitidos and p_dia not in dias_permitidos:
                continue
            p_ini = self._hora_a_slot(p['hora_inicio'])
            p_fin = self._hora_a_slot(p['hora_fin'])
            if slot_ini >= p_ini and slot_fin <= p_fin:
                if dias_validos and p['dia'] in [d['dia'] for d in dias_validos]:
                    continue
                dias_validos.append({
                    'dia': p['dia'],
                    'slot_inicio': slot_ini,
                    'slot_fin': slot_fin
                })
        if not dias_validos:
            print(f"[DEBUG MOTOR] SIN DIAS VALIDOS para {asignacion.get('materia_nombre','?')} ({asignacion.get('grupo_id','?')}) - slot_ini={slot_ini}, duracion={duracion}")
            print(f"[DEBUG MOTOR]   -> disponibilidad raw: {[{'dia':p['dia'],'hi':str(p['hora_inicio']),'hf':str(p['hora_fin'])} for p in asignacion.get('disponibilidad',[])]}")
        return dias_validos

    def es_posible_asignar(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']

        if slot_inicio + duracion_bloques > self.SLOTS_DIARIOS:
            return False

        for i in range(duracion_bloques):
            slot_actual = slot_inicio + i
            if self.ocupacion_salones.get((dia, salon_id, slot_actual)):
                return False
            if self.ocupacion_profesores.get((dia, prof_id, slot_actual)):
                return False
            if self.ocupacion_grupos.get((dia, grupo_id, slot_actual)):
                return False

        return True

    def registrar_ocupacion(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']

        for i in range(duracion_bloques):
            slot = slot_inicio + i
            self.ocupacion_salones[(dia, salon_id, slot)] = True
            self.ocupacion_profesores[(dia, prof_id, slot)] = True
            self.ocupacion_grupos[(dia, grupo_id, slot)] = True

        self.uso_salones[salon_id] = self.uso_salones.get(salon_id, 0) + duracion_bloques

    def _salones_compatibles(self, tipo_materia, es_mediacion):
        if es_mediacion:
            return sorted([s for s in self.salones if s.upper().startswith("MEDIACION_TECNOLOGICA")])

        resultado = []
        for s in self.salones:
            if s.upper().startswith("MEDIACION_TECNOLOGICA"):
                continue
            t = self.tipos_salones.get(s, 'Normal').lower()
            if tipo_materia == 'auditorio' and t == 'auditorio':
                resultado.append(s)
            elif tipo_materia == 'laboratorio' and t in ('laboratorio', 'normal'):
                resultado.append(s)
            elif tipo_materia in ('tecnologica', 'tecnológica') and t in ('tecnologica', 'tecnológica'):
                resultado.append(s)
            elif tipo_materia == 'normal' and t == 'normal':
                resultado.append(s)
        return sorted(resultado, key=lambda s: self.uso_salones.get(s, 0))

    def _asignar_dias_a_salon(self, asignacion, dias_disponibles, salon_id, horarios_generados):
        slot_ini = asignacion['slot_inicio']
        duracion = asignacion['slot_duracion']
        asignados = 0

        for dd in dias_disponibles:
            dia = dd['dia']
            if self.es_posible_asignar(asignacion, dia, slot_ini, duracion, salon_id):
                self.registrar_ocupacion(asignacion, dia, slot_ini, duracion, salon_id)
                horario = {
                    "asignacion_id": asignacion['asignacion_id'],
                    "salon_id": salon_id,
                    "dia": dia,
                    "hora_inicio": self._slot_a_hora(slot_ini),
                    "hora_fin": self._slot_a_hora(slot_ini + duracion)
                }
                horarios_generados.append(horario)
                asignados += 1

        return asignados

    @staticmethod
    def _tienen_conflicto_horario(a, b):
        dias_a = set()
        if a.get('dias'):
            for d in a['dias'].split(','):
                dias_a.add(GeneradorHorarios._normalizar_dia(d.strip()))
        dias_b = set()
        if b.get('dias'):
            for d in b['dias'].split(','):
                dias_b.add(GeneradorHorarios._normalizar_dia(d.strip()))
        if not dias_a.intersection(dias_b):
            return False
        slot_ini_a = a['slot_inicio']
        slot_fin_a = slot_ini_a + a['slot_duracion']
        slot_ini_b = b['slot_inicio']
        slot_fin_b = slot_ini_b + b['slot_duracion']
        return slot_ini_a < slot_fin_b and slot_ini_b < slot_fin_a

    def _generar_alternativas(self, asig, otros_conflictos):
        alternativas = []
        duracion = asig['slot_duracion']
        dias_asig = set()
        if asig.get('dias'):
            for d in asig['dias'].split(','):
                dias_asig.add(self._normalizar_dia(d.strip()))
        if not dias_asig:
            return alternativas
        tipo_materia = asig.get('tipo_materia', 'Normal').lower()
        es_mediacion = str(asig.get('modalidad', 'Presencial')) == 'Mediacion Tecnologica'
        salones = self._salones_compatibles(tipo_materia, es_mediacion)
        if not salones:
            return alternativas
        for dia in dias_asig:
            for p in asig.get('disponibilidad', []):
                if p['dia'] != dia:
                    continue
                p_ini = self._hora_a_slot(p['hora_inicio'])
                p_fin = self._hora_a_slot(p['hora_fin'])
                for test_ini in range(p_ini, p_fin - duracion + 1):
                    test_fin = test_ini + duracion
                    conflicted = False
                    for otro in otros_conflictos:
                        o_dias = set()
                        if otro.get('dias'):
                            for d in otro['dias'].split(','):
                                o_dias.add(self._normalizar_dia(d.strip()))
                        if dia in o_dias:
                            o_ini = otro['slot_inicio']
                            o_fin = o_ini + otro['slot_duracion']
                            if test_ini < o_fin and o_ini < test_fin:
                                conflicted = True
                                break
                    if not conflicted:
                        alternativas.append({
                            "dia": dia,
                            "hora_inicio": self._slot_a_hora(test_ini)[:5],
                            "hora_fin": self._slot_a_hora(test_fin)[:5],
                            "salon": salones[0]
                        })
                        break
        return alternativas[:3]

    def _crear_alerta_conflicto(self, asigs_en_conflicto, alternativas):
        conflictos = []
        for a in asigs_en_conflicto:
            conflictos.append({
                "asignacion_id": a['asignacion_id'],
                "materia": a.get('materia_nombre', '?').upper(),
                "materia_id": a.get('materia_id', '?'),
                "grupo": a.get('grupo_id', '?'),
                "profesor": a.get('profesor_nombre', '?').upper(),
                "profesor_id": a.get('profesor_id', '?'),
                "hora_inicio": a.get('hora_inicio', ''),
                "hora_fin": a.get('hora_fin', ''),
                "dias": a.get('dias', '')
            })
        materia_nombres = ", ".join([c['materia'] for c in conflictos])
        causas = [f"Las materias del grupo {asigs_en_conflicto[0]['grupo_id']} tienen horarios que se sobreponen."]
        sugerencias = ["Selecciona qué materia conserva su horario; las otras recibirán horarios alternativos sugeridos."]
        detalles_extra = [f"Asignaciones en conflicto: {materia_nombres}"]
        alerta = {
            "tipo": "conflicto",
            "materia": materia_nombres,
            "grupo": asigs_en_conflicto[0]['grupo_id'],
            "profesor": conflictos[0]['profesor'],
            "profesor_id": conflictos[0]['profesor_id'],
            "causas": causas,
            "sugerencias": sugerencias,
            "detalles_extra": detalles_extra,
            "conflictos": conflictos,
            "alternativas": alternativas
        }
        return alerta

    def _detectar_conflictos_grupo(self):
        from collections import defaultdict
        grupos = defaultdict(list)
        for idx, a in enumerate(self.asignaciones):
            a['_idx'] = idx
            grupos[a['grupo_id']].append(a)
        conflictos = []
        indices_a_remover = set()
        for grupo_id, asignaciones in grupos.items():
            if len(asignaciones) < 2:
                continue
            n = len(asignaciones)
            adyacencias = [[] for _ in range(n)]
            for i in range(n):
                for j in range(i + 1, n):
                    if self._tienen_conflicto_horario(asignaciones[i], asignaciones[j]):
                        adyacencias[i].append(j)
                        adyacencias[j].append(i)
            visitados = [False] * n
            for i in range(n):
                if visitados[i]:
                    continue
                componente = []
                stack = [i]
                visitados[i] = True
                while stack:
                    v = stack.pop()
                    componente.append(v)
                    for u in adyacencias[v]:
                        if not visitados[u]:
                            visitados[u] = True
                            stack.append(u)
                if len(componente) > 1:
                    asigs_conflicto = [asignaciones[idx] for idx in componente]
                    alternativas = {}
                    for a in asigs_conflicto:
                        otros = [x for x in asigs_conflicto if x['asignacion_id'] != a['asignacion_id']]
                        alternativas[a['asignacion_id']] = self._generar_alternativas(a, otros)
                    alerta = self._crear_alerta_conflicto(asigs_conflicto, alternativas)
                    conflictos.append(alerta)
                    for a in asigs_conflicto:
                        indices_a_remover.add(a['_idx'])
        self.asignaciones = [a for i, a in enumerate(self.asignaciones) if i not in indices_a_remover]
        for a in self.asignaciones:
            a.pop('_idx', None)
        return conflictos

    def ejecutar(self, modo="completo"):
        self.cargar_datos(modo)
        self._limpiar_matrices()

        if modo == "parcial":
            self._cargar_horarios_existentes()

        horarios_generados = []
        alertas_generadas = []

        conflictos_detectados = self._detectar_conflictos_grupo()
        alertas_generadas.extend(conflictos_detectados)
        if conflictos_detectados:
            print(f"\n[DEBUG MOTOR] *** {len(conflictos_detectados)} conflicto(s) de grupo detectado(s) y removido(s) del procesamiento automático")

        print(f"[DEBUG MOTOR] ===== INICIANDO ASIGNACION ({modo}) =====")
        print(f"[DEBUG MOTOR] Total asignaciones a procesar: {len(self.asignaciones)}")

        self.asignaciones.sort(
            key=lambda x: (
                0 if str(x.get('modalidad', 'Presencial')) != 'Mediacion Tecnologica' else 1,
                int(x.get('semestre_id', 99)),
                0 if x.get('tipo_materia', 'Normal').lower() in ('tecnologica', 'tecnológica', 'laboratorio') else 1,
                -float(x.get('horas_semana', 0))
            )
        )

        for idx, asignacion in enumerate(self.asignaciones):
            print(f"\n[DEBUG MOTOR] --- Procesando {idx+1}/{len(self.asignaciones)}: {asignacion.get('materia_nombre','?')} ({asignacion.get('grupo_id','?')}) ---")
            horas_totales = float(asignacion['horas_semana'])
            tipo_materia = asignacion.get('tipo_materia', 'Normal').lower()
            es_mediacion = str(asignacion.get('modalidad', 'Presencial')) == 'Mediacion Tecnologica'
            slot_ini = asignacion['slot_inicio']
            duracion = asignacion['slot_duracion']
            prof_nombre = asignacion.get('profesor_nombre', '?')
            mat_nombre = asignacion.get('materia_nombre', '?')
            grupo_id = asignacion.get('grupo_id', '?')

            dias_disponibles = self._dias_disponibles_para_horario(asignacion)
            salones_compatibles = self._salones_compatibles(tipo_materia, es_mediacion)

            print(f"[DEBUG MOTOR]   Dias disponibles: {[d['dia'] for d in dias_disponibles]}")
            print(f"[DEBUG MOTOR]   Salones compatibles: {salones_compatibles[:3]}...")

            if not dias_disponibles:
                causas = ["El profesor no tiene disponibilidad en el horario requerido."]
                sugerencias = ["Verificar que la disponibilidad del profesor cubra el horario de la asignación."]
                detalles_extra = [f"Horario requerido: {self._slot_a_hora(slot_ini)[:5]}-{self._slot_a_hora(slot_ini+duracion)[:5]}"]
                alerta = {"materia": mat_nombre.upper(), "materia_id": asignacion['materia_id'], "grupo": grupo_id, "profesor": prof_nombre.upper(), "profesor_id": asignacion['profesor_id'], "causas": causas, "sugerencias": sugerencias, "detalles_extra": detalles_extra}
                alertas_generadas.append(alerta)
                print(f"ALERTA: {mat_nombre} ({grupo_id}) - Sin disponibilidad del profesor para el horario requerido")
                continue

            if not salones_compatibles:
                causas = [f"No hay salones MEDIACION_TECNOLOGICA disponibles." if es_mediacion else f"No hay salones compatibles de tipo '{tipo_materia}'."]
                sugerencias = ["Verificar que existan salones de tipo Mediacion Tecnologica." if es_mediacion else f"Registrar salones tipo '{tipo_materia}' o cambiar el tipo de la materia."]
                detalles_extra = [f"Modalidad: {'Mediacion Tecnologica' if es_mediacion else 'Presencial'}, Tipo materia: {tipo_materia}"]
                alerta = {"materia": mat_nombre.upper(), "materia_id": asignacion['materia_id'], "grupo": grupo_id, "profesor": prof_nombre.upper(), "profesor_id": asignacion['profesor_id'], "causas": causas, "sugerencias": sugerencias, "detalles_extra": detalles_extra}
                alertas_generadas.append(alerta)
                print(f"ALERTA: {mat_nombre} ({grupo_id}) - Sin salones compatibles ({'MT' if es_mediacion else tipo_materia})")
                continue

            bkey = (asignacion['profesor_id'], asignacion['materia_id'])

            salon_preferido = self.salon_por_materia_profesor.get(bkey)

            asignado_completamente = False

            if salon_preferido and salon_preferido in salones_compatibles:
                n = self._asignar_dias_a_salon(asignacion, dias_disponibles, salon_preferido, horarios_generados)
                if n > 0:
                    asignado_completamente = True

            if not asignado_completamente:
                for salon in salones_compatibles:
                    if self._asignar_dias_a_salon(asignacion, dias_disponibles, salon, horarios_generados) > 0:
                        self.salon_por_materia_profesor[bkey] = salon
                        asignado_completamente = True
                        break

            if not asignado_completamente:
                prof_nombre = asignacion.get('profesor_nombre', '?')
                mat_nombre = asignacion.get('materia_nombre', '?')
                grupo_id = asignacion.get('grupo_id', '?')

                causas = []
                sugerencias = []

                if not salones_compatibles:
                    if es_mediacion:
                        causas.append("No hay salones MEDIACION_TECNOLOGICA disponibles.")
                        sugerencias.append("Verificar que existan salones de tipo Mediacion Tecnologica.")
                    else:
                        causas.append(f"No hay salones compatibles de tipo '{tipo_materia}'.")
                        sugerencias.append(f"Registrar salones tipo '{tipo_materia}' o cambiar el tipo de la materia.")

                if dias_disponibles:
                    causas.append("Todos los salones compatibles están ocupados en los días/horarios disponibles.")
                    sugerencias.append("Ampliar el horario del profesor o agregar más salones.")
                else:
                    causas.append("El profesor no tiene disponibilidad en el horario requerido.")
                    sugerencias.append("Verificar que la disponibilidad del profesor cubra el horario de la asignación.")

                detalles_extra = []
                detalles_extra.append(f"Horas requeridas: {horas_totales}h")
                detalles_extra.append(f"Días disponibles para el horario: {len(dias_disponibles)}")
                if dias_disponibles:
                    for d in dias_disponibles:
                        detalles_extra.append(f"  {d['dia']}: {self._slot_a_hora(slot_ini)[:5]}-{self._slot_a_hora(slot_ini+duracion)[:5]}")
                if salones_compatibles:
                    libres = []
                    for s in salones_compatibles[:5]:
                        for dd in dias_disponibles:
                            if self.es_posible_asignar(asignacion, dd['dia'], slot_ini, duracion, s):
                                libres.append(f"{s} ({dd['dia']})")
                                break
                    if libres:
                        detalles_extra.append(f"Salones con espacio: {', '.join(libres[:3])}")

                alerta = {
                    "materia": mat_nombre.upper(),
                    "materia_id": asignacion['materia_id'],
                    "grupo": grupo_id,
                    "profesor": prof_nombre.upper(),
                    "profesor_id": asignacion['profesor_id'],
                    "causas": causas,
                    "sugerencias": sugerencias[:3],
                    "detalles_extra": detalles_extra
                }
                alertas_generadas.append(alerta)
                causa_corta = causas[0] if causas else "sin causa identificada"
                print(f"ALERTA: No se pudo asignar {mat_nombre} ({grupo_id}) - {causa_corta}")

        self.guardar_en_bd(horarios_generados, modo)

        return len(horarios_generados), alertas_generadas

    def guardar_en_bd(self, lista_horarios, modo="completo"):
        try:
            if modo == "completo":
                self.cursor.execute("TRUNCATE TABLE horarios")
                self.cursor.execute("UPDATE asignaciones SET estado = 'pendiente'")

            sql_insert = """INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                     VALUES (%s, %s, %s, %s, %s)"""

            print(f"[DEBUG GUARDAR] Horarios a insertar: {len(lista_horarios)}")
            for h in lista_horarios:
                vals = (h['asignacion_id'], h['salon_id'], h['dia'], h['hora_inicio'], h['hora_fin'])
                print(f"[DEBUG GUARDAR]   INSERT: asig={vals[0]} salon={vals[1]!r} dia={vals[2]!r} ini={vals[3]!r} fin={vals[4]!r}")
                self.cursor.execute(sql_insert, vals)

            if lista_horarios:
                ids_asignados = list(set([str(h['asignacion_id']) for h in lista_horarios]))
                format_strings = ','.join(['%s'] * len(ids_asignados))
                sql_update = f"UPDATE asignaciones SET estado = 'asignado' WHERE asignacion_id IN ({format_strings})"
                self.cursor.execute(sql_update, tuple(ids_asignados))

            self.conexion.commit()

            # Verify what was stored
            self.cursor.execute("SELECT horario_id, salon_id, dia, hora_inicio, hora_fin FROM horarios ORDER BY horario_id")
            rows = self.cursor.fetchall()
            print(f"[DEBUG GUARDAR] VERIFICACION: {len(rows)} horarios en BD tras commit:")
            for r in rows:
                print(f"[DEBUG GUARDAR]   BD: id={r['horario_id']} salon={r['salon_id']!r} dia={r['dia']!r} ini={r['hora_inicio']} fin={r['hora_fin']}")
        except Exception as e:
            print(f"[DEBUG GUARDAR] ERROR: {e}")
            import traceback
            traceback.print_exc()
            self.conexion.rollback()
            raise e
