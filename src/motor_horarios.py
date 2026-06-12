import mysql.connector
import datetime
import math

class GeneradorHorarios:
    def __init__(self, conexion):
        self.conexion = conexion
        self.cursor = self.conexion.cursor(dictionary=True)

        self.HORA_INICIO_CLASES = 7
        self.MINUTOS_BLOQUE = 30
        self.SLOTS_DIARIOS = 30

        self.ocupacion_salones = {}
        self.ocupacion_profesores = {}
        self.ocupacion_grupos = {}
        self.uso_salones = {}
        self.tipos_salones = {}

    def _limpiar_matrices(self):
        self.ocupacion_salones = {}
        self.ocupacion_profesores = {}
        self.ocupacion_grupos = {}
        self.uso_salones = {salon: 0 for salon in self.salones}

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
                   p.nombre as profesor_nombre,
                   p.en_linea,
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
            disp_por_profesor[pid].append({
                'dia': f['dia'],
                'hora_inicio': f['hora_inicio'],
                'hora_fin': f['hora_fin']
            })

        for asig in self.asignaciones:
            asig['disponibilidad'] = disp_por_profesor.get(asig['profesor_id'], [])

        self.cursor.execute("SELECT salon_id, tipo FROM salones")
        salones_bd = self.cursor.fetchall()
        self.salones = [row['salon_id'] for row in salones_bd]
        self.tipos_salones = {row['salon_id']: (row['tipo'] or 'Normal') for row in salones_bd}

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

    def es_posible_asignar(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']
        es_en_linea = str(asignacion.get('en_linea', 'NO')).upper() in ['SI', 'SÍ']

        if slot_inicio + duracion_bloques > self.SLOTS_DIARIOS:
            return False

        disponibilidad = asignacion.get('disponibilidad', [])
        if not disponibilidad:
            return False

        periodo_valido = None
        for p in disponibilidad:
            if p['dia'] == dia:
                inicio_profe = self._hora_a_slot(p['hora_inicio'])
                fin_profe = self._hora_a_slot(p['hora_fin'])
                if slot_inicio >= inicio_profe and (slot_inicio + duracion_bloques) <= fin_profe:
                    periodo_valido = p
                    break

        if periodo_valido is None:
            return False

        if es_en_linea:
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

    def _evaluar_slot(self, grupo_id, dia, slot_inicio, duracion_bloques):
        ocupados = [slot for (d, g, slot) in self.ocupacion_grupos.keys() if d == dia and g == grupo_id]
        if not ocupados:
            return 100 - slot_inicio

        nuevo_rango = set(range(slot_inicio, slot_inicio + duracion_bloques))
        min_dist = 999
        for n in nuevo_rango:
            for o in ocupados:
                dist = abs(n - o)
                if dist < min_dist:
                    min_dist = dist

        distancia_real = min_dist - 1
        if distancia_real == 1:
            return 200
        elif distancia_real == 0:
            return 150
        else:
            return -(distancia_real * 50)

    def intentar_asignar_estrategia_simetrica_mixta(self, asignacion, estrategia, salon_norm, salon_tec, horarios_generados):
        mejores_opciones = []
        grupo_id = asignacion['grupo_id']

        for slot_inicio in range(self.SLOTS_DIARIOS):
            posible_todos = True
            for i, (dia, duracion_bloques) in enumerate(estrategia):
                salon_a_usar = salon_tec if (i % 2 != 0 or len(estrategia) == 1) else salon_norm
                if not self.es_posible_asignar(asignacion, dia, slot_inicio, duracion_bloques, salon_a_usar):
                    posible_todos = False
                    break

            if posible_todos:
                score_total = sum(self._evaluar_slot(grupo_id, dia, slot_inicio, duracion_bloques) for dia, duracion_bloques in estrategia)
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

        for slot_inicio in range(self.SLOTS_DIARIOS):
            posible_todos = True
            for dia, duracion_bloques in estrategia:
                if not self.es_posible_asignar(asignacion, dia, slot_inicio, duracion_bloques, salon):
                    posible_todos = False
                    break

            if posible_todos:
                score_total = sum(self._evaluar_slot(grupo_id, dia, slot_inicio, duracion_bloques) for dia, duracion_bloques in estrategia)
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

        for slot_inicio in range(self.SLOTS_DIARIOS):
            if self.es_posible_asignar(asignacion, dia, slot_inicio, duracion_bloques, salon):
                score = self._evaluar_slot(grupo_id, dia, slot_inicio, duracion_bloques)
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

        self.asignaciones.sort(
            key=lambda x: (
                1 if str(x.get('en_linea', 'NO')).upper() in ['SI', 'SÍ'] else 0,
                int(x.get('semestre_id', 99)),
                0 if x.get('tipo_materia', 'Normal').lower() in ['tecnológica', 'tecnologica', 'laboratorio'] else 1,
                -float(x.get('horas_semana', 0))
            )
        )

        for asignacion in self.asignaciones:
            horas_totales = float(asignacion['horas_semana'])
            bloques_totales = int(horas_totales * 2)
            tipo_materia = asignacion.get('tipo_materia', 'Normal').lower()
            es_en_linea = str(asignacion.get('en_linea', 'NO')).upper() in ['SI', 'SÍ']

            if bloques_totales >= 6:
                b_mitad1 = math.ceil(bloques_totales / 2)
                b_mitad2 = bloques_totales - b_mitad1
                b_mayor = 4 if bloques_totales == 6 else b_mitad1
                b_menor = 2 if bloques_totales == 6 else b_mitad2

                estrategias = [
                    [("Lunes", b_mitad1), ("Miércoles", b_mitad2)],
                    [("Martes", b_mitad1), ("Jueves", b_mitad2)],
                    [("Miércoles", b_mitad1), ("Viernes", b_mitad2)],
                    [("Jueves", b_mitad1), ("Sábado", b_mitad2)],
                    [("Viernes", b_mitad1), ("Sábado", b_mitad2)],
                    [("Lunes", b_mitad1), ("Jueves", b_mitad2)],
                    [("Martes", b_mitad1), ("Viernes", b_mitad2)],
                    [("Lunes", b_mayor), ("Miércoles", b_menor)],
                    [("Martes", b_mayor), ("Jueves", b_menor)],
                    [("Viernes", b_mayor), ("Sábado", b_menor)],
                    [("Lunes", b_menor), ("Miércoles", b_mayor)],
                    [("Martes", b_menor), ("Jueves", b_mayor)],
                    [("Viernes", b_menor), ("Sábado", b_mayor)]
                ]
                if bloques_totales == 8:
                    estrategias.extend([
                        [("Lunes", 2), ("Martes", 2), ("Miércoles", 2), ("Jueves", 2)],
                        [("Martes", 2), ("Miércoles", 2), ("Jueves", 2), ("Viernes", 2)],
                        [("Miércoles", 2), ("Jueves", 2), ("Viernes", 2), ("Sábado", 2)],
                        [("Lunes", 4), ("Miércoles", 2), ("Viernes", 2)]
                    ])
                estrategias.extend([[("Lunes", bloques_totales)], [("Martes", bloques_totales)], [("Miércoles", bloques_totales)], [("Jueves", bloques_totales)], [("Viernes", bloques_totales)], [("Sábado", bloques_totales)]])
            else:
                estrategias = [[("Lunes", bloques_totales)], [("Martes", bloques_totales)], [("Miércoles", bloques_totales)], [("Jueves", bloques_totales)], [("Viernes", bloques_totales)], [("Sábado", bloques_totales)]]

            asignado_completamente = False

            if es_en_linea:
                salones_priorizados = sorted([s for s in self.salones if s.upper().startswith("EN_LINEA")])

                for salon in salones_priorizados:
                    if asignado_completamente:
                        break
                    for estrategia in estrategias:
                        horarios_temporales = []
                        if self.intentar_asignar_estrategia_simetrica(asignacion, estrategia, salon, horarios_temporales):
                            horarios_generados.extend(horarios_temporales)
                            asignado_completamente = True
                            break

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

            elif tipo_materia == 'laboratorio':
                salones_lab = [s for s in self.salones if self.tipos_salones.get(s, 'Normal').lower() == 'laboratorio' and not s.upper().startswith("EN_LINEA")]
                salones_norm = [s for s in self.salones if self.tipos_salones.get(s, 'Normal').lower() == 'normal' and not s.upper().startswith("EN_LINEA")]

                salones_lab_ordenados = sorted(salones_lab, key=lambda s: self.uso_salones.get(s, 0))
                salones_norm_ordenados = sorted(salones_norm, key=lambda s: self.uso_salones.get(s, 0))

                if salones_lab_ordenados and salones_norm_ordenados:
                    for s_norm in salones_norm_ordenados:
                        if asignado_completamente:
                            break
                        for s_lab in salones_lab_ordenados:
                            if asignado_completamente:
                                break
                            for estrategia in estrategias:
                                horarios_temporales = []
                                if self.intentar_asignar_estrategia_simetrica_mixta(asignacion, estrategia, s_norm, s_lab, horarios_temporales):
                                    horarios_generados.extend(horarios_temporales)
                                    asignado_completamente = True
                                    break

                    if not asignado_completamente:
                        for s_norm in salones_norm_ordenados:
                            if asignado_completamente:
                                break
                            for s_lab in salones_lab_ordenados:
                                if asignado_completamente:
                                    break
                                for estrategia in estrategias:
                                    exito_estrategia = True
                                    horarios_temporales = []
                                    for i, (dia, bloques_requeridos) in enumerate(estrategia):
                                        salon_a_usar = s_lab if (i % 2 != 0 or len(estrategia) == 1) else s_norm
                                        exito_bloque = self.intentar_asignar_bloque(asignacion, dia, bloques_requeridos, salon_a_usar, horarios_temporales)
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

            if not asignado_completamente and not es_en_linea:
                salones_norm = [s for s in self.salones if self.tipos_salones.get(s, 'Normal').lower() == 'normal' and not s.upper().startswith("EN_LINEA")]
                salones_tec = [s for s in self.salones if self.tipos_salones.get(s, 'Normal').lower() in ['tecnológica', 'tecnologica'] and not s.upper().startswith("EN_LINEA")]
                salones_lab = [s for s in self.salones if self.tipos_salones.get(s, 'Normal').lower() == 'laboratorio' and not s.upper().startswith("EN_LINEA")]

                salones_norm_ordenados = sorted(salones_norm, key=lambda s: self.uso_salones.get(s, 0))
                salones_tec_ordenados = sorted(salones_tec, key=lambda s: self.uso_salones.get(s, 0))
                salones_lab_ordenados = sorted(salones_lab, key=lambda s: self.uso_salones.get(s, 0))

                if tipo_materia in ['tecnológica', 'tecnologica']:
                    salones_priorizados = salones_tec_ordenados
                elif tipo_materia == 'laboratorio':
                    salones_priorizados = salones_lab_ordenados + salones_norm_ordenados
                else:
                    salones_priorizados = salones_norm_ordenados + salones_tec_ordenados + salones_lab_ordenados

                for salon in salones_priorizados:
                    if asignado_completamente:
                        break
                    for estrategia in estrategias:
                        horarios_temporales = []
                        if self.intentar_asignar_estrategia_simetrica(asignacion, estrategia, salon, horarios_temporales):
                            horarios_generados.extend(horarios_temporales)
                            asignado_completamente = True
                            break

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
                            if s.upper().startswith("EN_LINEA"):
                                continue
                            t_salon = self.tipos_salones.get(s, 'Normal').lower()

                            if tipo_mat == 'laboratorio' and t_salon in ['laboratorio', 'normal']:
                                salones_compatibles.append(s)
                            elif tipo_mat in ['tecnológica', 'tecnologica'] and t_salon in ['tecnológica', 'tecnologica']:
                                salones_compatibles.append(s)
                            elif tipo_mat == 'normal':
                                salones_compatibles.append(s)

                        if not salones_compatibles:
                            causas.append(f"No hay salones disponibles de tipo '{tipo_mat}' para esta materia.")
                            if tipo_mat == 'laboratorio':
                                sugerencias.append(f"Registrar salones tipo 'Laboratorio' o cambiar la materia a 'Normal'.")
                            elif tipo_mat in ['tecnológica', 'tecnologica']:
                                sugerencias.append(f"Registrar salones tipo 'Tecnológica' o cambiar la materia a 'Normal'.")
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

                alerta = (
                    f"Materia: {mat_nombre.upper()} (Grupo {grupo_id})\n"
                    f"Profesor: {prof_nombre.upper()}\n"
                    f"Detalle: {'; '.join(causas)}\n"
                    f"Sugerencias: {' | '.join(sugerencias[:3])}"
                )
                alertas_generadas.append(alerta)
                causa_corta = causas[0] if causas else "sin causa identificada"
                print(f"ALERTA: No se pudo asignar {mat_nombre} ({grupo_id}) - {causa_corta}")

        self.guardar_en_bd(horarios_generados, modo)

        return len(horarios_generados), alertas_generadas

    def _deshacer_ocupacion(self, asignacion, dia, slot_inicio, salon_id, duracion_bloques):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']

        for i in range(duracion_bloques):
            slot = slot_inicio + i
            if (dia, salon_id, slot) in self.ocupacion_salones:
                del self.ocupacion_salones[(dia, salon_id, slot)]
            if (dia, prof_id, slot) in self.ocupacion_profesores:
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
                self.cursor.execute("TRUNCATE TABLE horarios")
                self.cursor.execute("UPDATE asignaciones SET estado = 'pendiente'")

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

            self.conexion.commit()
        except Exception as e:
            self.conexion.rollback()
            raise e
