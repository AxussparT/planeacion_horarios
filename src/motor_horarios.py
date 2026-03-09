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
        
        # --- NUEVO: Traemos p.en_linea ---
        sql_asignaciones = f"""
            SELECT a.asignacion_id, a.profesor_id, a.materia_id, a.grupo_id, 
                   p.disponible_inicio, p.disponible_fin, p.dias_disponibles,
                   IFNULL(m.horas_semana, 4) as horas_semana,
                   IFNULL(m.tipo, 'Normal') as tipo_materia,
                   IFNULL(m.semestre_id, 99) as semestre_id,
                   IFNULL(p.en_linea, 'NO') as en_linea
            FROM asignaciones a
            JOIN profesores p ON a.profesor_id = p.profesor_id
            JOIN materias m ON a.materia_id = m.materia_id
            {filtro_estado}
        """
        self.cursor.execute(sql_asignaciones)
        self.asignaciones = self.cursor.fetchall()

        self.cursor.execute("SELECT salon_id, tipo FROM salones")
        salones_bd = self.cursor.fetchall()
        self.salones = [row['salon_id'] for row in salones_bd]
        self.tipos_salones = {row['salon_id']: (row['tipo'] or 'Normal') for row in salones_bd}

    def _cargar_horarios_existentes(self):
        sql = """
            SELECT h.salon_id, h.dia, h.hora_inicio, h.hora_fin, 
                   a.profesor_id, a.grupo_id, IFNULL(p.en_linea, 'NO') as en_linea
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
            es_en_linea = str(h['en_linea']).upper() == 'SI'
            
            slot_inicio = self._hora_a_slot(h['hora_inicio'])
            slot_fin = self._hora_a_slot(h['hora_fin'])
            duracion = slot_fin - slot_inicio
            
            for i in range(duracion):
                slot_actual = slot_inicio + i
                if not es_en_linea:
                    self.ocupacion_salones[(dia, salon_id, slot_actual)] = True
                self.ocupacion_profesores[(dia, prof_id, slot_actual)] = True
                self.ocupacion_grupos[(dia, grupo_id, slot_actual)] = True
                
            if not es_en_linea:
                self.uso_salones[salon_id] = self.uso_salones.get(salon_id, 0) + duracion

    def es_posible_asignar(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']
        es_en_linea = str(asignacion.get('en_linea', 'NO')).upper() == 'SI'

        # --- REGLA: EN LÍNEA DE 16:00 A 21:00 (Slots 18 a 28) ---
        if es_en_linea:
            if slot_inicio < 18 or (slot_inicio + duracion_bloques) > 28:
                return False

        if slot_inicio + duracion_bloques > self.SLOTS_DIARIOS:
            return False

        if not asignacion['disponible_inicio'] or not asignacion['disponible_fin'] or not asignacion['dias_disponibles']:
            return False

        inicio_profe = self._hora_a_slot(asignacion['disponible_inicio'])
        fin_profe = self._hora_a_slot(asignacion['disponible_fin'])
        
        if slot_inicio < inicio_profe or (slot_inicio + duracion_bloques) > fin_profe:
            return False

        if dia not in asignacion['dias_disponibles']: 
            return False

        # --- REGLA: 2 HORAS DE DESCANSO PARA PROFESORES MIXTOS ---
        if es_en_linea:
            # Quitamos el '-L' de la cuenta para buscar si dio clases presenciales hoy
            base_prof_id = prof_id.replace('-L', '').replace('-l', '')
            max_slot_presencial = -1
            
            for (d, p, s) in self.ocupacion_profesores.keys():
                if d == dia and p == base_prof_id:
                    if s > max_slot_presencial:
                        max_slot_presencial = s
                        
            # Si dio presencial hoy, exigimos 4 slots (2 horas) libres
            if max_slot_presencial != -1:
                if slot_inicio < (max_slot_presencial + 5):
                    return False

        for i in range(duracion_bloques):
            slot_actual = slot_inicio + i
            # Las clases en línea no revisan la ocupación del salón físico
            if not es_en_linea and self.ocupacion_salones.get((dia, salon_id, slot_actual)): return False
            if self.ocupacion_profesores.get((dia, prof_id, slot_actual)): return False
            if self.ocupacion_grupos.get((dia, grupo_id, slot_actual)): return False

        return True

    def registrar_ocupacion(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']
        es_en_linea = str(asignacion.get('en_linea', 'NO')).upper() == 'SI'
        
        for i in range(duracion_bloques):
            slot = slot_inicio + i
            if not es_en_linea:
                self.ocupacion_salones[(dia, salon_id, slot)] = True
            self.ocupacion_profesores[(dia, prof_id, slot)] = True
            self.ocupacion_grupos[(dia, grupo_id, slot)] = True
            
        if not es_en_linea:
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
            return - (distancia_real * 50) 

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

    def ejecutar(self, modo="completo"):
        self.cargar_datos(modo)
        self._limpiar_matrices()
        
        if modo == "parcial":
            self._cargar_horarios_existentes()
        
        horarios_generados = []
        
        # --- NUEVO: Asignar Presencial PRIMERO, luego En Línea ---
        self.asignaciones.sort(
            key=lambda x: (
                1 if str(x.get('en_linea', 'NO')).upper() == 'SI' else 0,
                int(x.get('semestre_id', 99)), 
                0 if x.get('tipo_materia', 'Normal').lower() in ['tecnológica', 'tecnologica', 'laboratorio'] else 1, 
                -float(x.get('horas_semana', 0))
            )
        )

        print(f"--- Encontradas {len(self.asignaciones)} asignaciones pendientes en modo {modo} ---")

        for asignacion in self.asignaciones:
            horas_totales = float(asignacion['horas_semana'])
            bloques_totales = int(horas_totales * 2) 
            tipo_materia = asignacion.get('tipo_materia', 'Normal').lower()
            es_en_linea = str(asignacion.get('en_linea', 'NO')).upper() == 'SI'
            
            if bloques_totales >= 6:
                b_mitad1 = math.ceil(bloques_totales/2)
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
                
                estrategias.extend([
                    [("Lunes", bloques_totales)], [("Martes", bloques_totales)], 
                    [("Miércoles", bloques_totales)], [("Jueves", bloques_totales)], 
                    [("Viernes", bloques_totales)], [("Sábado", bloques_totales)]
                ])
                
            else:
                estrategias = [
                    [("Lunes", bloques_totales)], [("Martes", bloques_totales)], 
                    [("Miércoles", bloques_totales)], [("Jueves", bloques_totales)], 
                    [("Viernes", bloques_totales)], [("Sábado", bloques_totales)]
                ]

            asignado_completamente = False
            
            # --- ASIGNACIÓN DE SALÓN VIRTUAL O FÍSICO ---
            if es_en_linea:
                salones_priorizados = ["EN_LINEA"] # Creamos un salón infinito y virtual
            else:
                salones_tec = [s for s in self.salones if self.tipos_salones.get(s, 'Normal').lower() in ['tecnológica', 'tecnologica', 'laboratorio']]
                salones_norm = [s for s in self.salones if self.tipos_salones.get(s, 'Normal').lower() == 'normal']
                
                salones_tec_ordenados = sorted(salones_tec, key=lambda s: self.uso_salones.get(s, 0))
                salones_norm_ordenados = sorted(salones_norm, key=lambda s: self.uso_salones.get(s, 0))
                
                if tipo_materia in ['tecnológica', 'tecnologica', 'laboratorio']:
                    salones_priorizados = salones_tec_ordenados
                else:
                    salones_priorizados = salones_norm_ordenados + salones_tec_ordenados
            
            for salon in salones_priorizados:
                if asignado_completamente: break
                for estrategia in estrategias:
                    horarios_temporales = []
                    if self.intentar_asignar_estrategia_simetrica(asignacion, estrategia, salon, horarios_temporales):
                        horarios_generados.extend(horarios_temporales)
                        asignado_completamente = True
                        break

            if not asignado_completamente:
                for salon in salones_priorizados:
                    if asignado_completamente: break
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
                print(f"ALERTA: No se pudo asignar ID {asignacion['asignacion_id']} ({horas_totales} hrs)")

        self.guardar_en_bd(horarios_generados, modo)
        return len(horarios_generados)

    def _deshacer_ocupacion(self, asignacion, dia, slot_inicio, salon_id, duracion_bloques):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']
        es_en_linea = str(asignacion.get('en_linea', 'NO')).upper() == 'SI'
        
        for i in range(duracion_bloques):
            slot = slot_inicio + i
            if not es_en_linea and (dia, salon_id, slot) in self.ocupacion_salones: 
                del self.ocupacion_salones[(dia, salon_id, slot)]
            if (dia, prof_id, slot) in self.ocupacion_profesores: 
                del self.ocupacion_profesores[(dia, prof_id, slot)]
            if (dia, grupo_id, slot) in self.ocupacion_grupos: 
                del self.ocupacion_grupos[(dia, grupo_id, slot)]
        
        if not es_en_linea:
            self.uso_salones[salon_id] -= duracion_bloques

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