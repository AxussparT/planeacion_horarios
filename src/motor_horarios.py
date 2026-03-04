import mysql.connector
import datetime 
import math

class GeneradorHorarios:
    def __init__(self, conexion):
        self.conexion = conexion
        self.cursor = self.conexion.cursor(dictionary=True)
        
        self.HORA_INICIO_CLASES = 7 
        self.MINUTOS_BLOQUE = 30
        self.SLOTS_DIARIOS = 29 
        
        self.ocupacion_salones = {} 
        self.ocupacion_profesores = {} 
        self.ocupacion_grupos = {}     
        self.uso_salones = {} 

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

    def cargar_datos(self):
        sql_asignaciones = """
            SELECT a.asignacion_id, a.profesor_id, a.materia_id, a.grupo_id, 
                   p.disponible_inicio, p.disponible_fin, p.dias_disponibles,
                   IFNULL(m.horas_semana, 4) as horas_semana
            FROM asignaciones a
            JOIN profesores p ON a.profesor_id = p.profesor_id
            JOIN materias m ON a.materia_id = m.materia_id
        """
        self.cursor.execute(sql_asignaciones)
        self.asignaciones = self.cursor.fetchall()

        self.cursor.execute("SELECT salon_id FROM salones")
        self.salones = [row['salon_id'] for row in self.cursor.fetchall()]

    def es_posible_asignar(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']

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

        for i in range(duracion_bloques):
            slot_actual = slot_inicio + i
            if self.ocupacion_salones.get((dia, salon_id, slot_actual)): return False
            if self.ocupacion_profesores.get((dia, prof_id, slot_actual)): return False
            if self.ocupacion_grupos.get((dia, grupo_id, slot_actual)): return False

        return True

    def registrar_ocupacion(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']
        
        for i in range(duracion_bloques):
            slot = slot_inicio + i
            self.ocupacion_salones[(dia, salon_id, slot)] = True
            self.ocupacion_profesores[(dia, prof_id, slot)] = True
            self.ocupacion_grupos[(dia, grupo_id, slot)] = True
            
        self.uso_salones[salon_id] += duracion_bloques

    # --- NUEVO MÉTODO: Intenta forzar la misma hora para todos los días ---
    def intentar_asignar_estrategia_simetrica(self, asignacion, estrategia, salon, horarios_generados):
        """Busca un único slot de inicio que esté disponible para todos los días de la estrategia."""
        for slot_inicio in range(self.SLOTS_DIARIOS):
            posible_todos = True
            
            # Verificamos si la MISMA hora exacta está libre para Lunes y para Miércoles
            for dia, duracion_bloques in estrategia:
                if not self.es_posible_asignar(asignacion, dia, slot_inicio, duracion_bloques, salon):
                    posible_todos = False
                    break
            
            if posible_todos:
                # Si caben simétricamente, los registramos
                for dia, duracion_bloques in estrategia:
                    self.registrar_ocupacion(asignacion, dia, slot_inicio, duracion_bloques, salon)
                    horario = {
                        "asignacion_id": asignacion['asignacion_id'], 
                        "salon_id": salon,
                        "dia": dia,
                        "hora_inicio": self._slot_a_hora(slot_inicio),
                        "hora_fin": self._slot_a_hora(slot_inicio + duracion_bloques)
                    }
                    horarios_generados.append(horario)
                return True
                
        return False

    def intentar_asignar_bloque(self, asignacion, dia, duracion_bloques, salon, horarios_generados):
        for slot in range(self.SLOTS_DIARIOS):
            if self.es_posible_asignar(asignacion, dia, slot, duracion_bloques, salon):
                self.registrar_ocupacion(asignacion, dia, slot, duracion_bloques, salon)
                horario = {
                    "asignacion_id": asignacion['asignacion_id'], 
                    "salon_id": salon,
                    "dia": dia,
                    "hora_inicio": self._slot_a_hora(slot),
                    "hora_fin": self._slot_a_hora(slot + duracion_bloques)
                }
                horarios_generados.append(horario)
                return True
        return False

    def ejecutar(self):
        self.cargar_datos()
        self._limpiar_matrices()
        
        horarios_generados = []
        
        self.asignaciones.sort(key=lambda x: float(x.get('horas_semana', 0)), reverse=True)

        for asignacion in self.asignaciones:
            horas_totales = float(asignacion['horas_semana'])
            bloques_totales = int(horas_totales * 2) 
            
            if bloques_totales >= 6:
                b_mitad1 = math.ceil(bloques_totales/2)
                b_mitad2 = bloques_totales - b_mitad1
                
                b_mayor = 4 if bloques_totales == 6 else b_mitad1
                b_menor = 2 if bloques_totales == 6 else b_mitad2
                
                estrategias = [
                    [("Lunes", b_mitad1), ("Miércoles", b_mitad2)],
                    [("Martes", b_mitad1), ("Jueves", b_mitad2)],
                    [("Miércoles", b_mitad1), ("Viernes", b_mitad2)],
                    [("Lunes", b_mitad1), ("Jueves", b_mitad2)],
                    [("Martes", b_mitad1), ("Viernes", b_mitad2)],
                    [("Lunes", b_mayor), ("Miércoles", b_menor)],
                    [("Martes", b_mayor), ("Jueves", b_menor)],
                    [("Lunes", b_menor), ("Miércoles", b_mayor)],
                    [("Martes", b_menor), ("Jueves", b_mayor)],
                    [("Lunes", bloques_totales)], [("Martes", bloques_totales)], 
                    [("Miércoles", bloques_totales)], [("Jueves", bloques_totales)], [("Viernes", bloques_totales)]
                ]
            else:
                estrategias = [
                    [("Lunes", bloques_totales)], [("Martes", bloques_totales)], 
                    [("Miércoles", bloques_totales)], [("Jueves", bloques_totales)], [("Viernes", bloques_totales)]
                ]

            asignado_completamente = False
            salones_ordenados = sorted(self.salones, key=lambda s: self.uso_salones.get(s, 0))
            
            # --- FASE 1: BÚSQUEDA ESTRICTA SIMÉTRICA ---
            for salon in salones_ordenados:
                if asignado_completamente: break
                for estrategia in estrategias:
                    horarios_temporales = []
                    # Intentamos que empiecen exactamente a la misma hora
                    if self.intentar_asignar_estrategia_simetrica(asignacion, estrategia, salon, horarios_temporales):
                        horarios_generados.extend(horarios_temporales)
                        asignado_completamente = True
                        break

            # --- FASE 2: RESPALDO ASIMÉTRICO (Si falló la simetría) ---
            if not asignado_completamente:
                for salon in salones_ordenados:
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

        self.guardar_en_bd(horarios_generados)
        return len(horarios_generados)

    def _deshacer_ocupacion(self, asignacion, dia, slot_inicio, salon_id, duracion_bloques):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']
        for i in range(duracion_bloques):
            slot = slot_inicio + i
            if (dia, salon_id, slot) in self.ocupacion_salones: del self.ocupacion_salones[(dia, salon_id, slot)]
            if (dia, prof_id, slot) in self.ocupacion_profesores: del self.ocupacion_profesores[(dia, prof_id, slot)]
            if (dia, grupo_id, slot) in self.ocupacion_grupos: del self.ocupacion_grupos[(dia, grupo_id, slot)]
        
        self.uso_salones[salon_id] -= duracion_bloques

    def guardar_en_bd(self, lista_horarios):
        try:
            self.cursor.execute("TRUNCATE TABLE horarios") 
            sql = """INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin) 
                     VALUES (%s, %s, %s, %s, %s)"""
            valores = [(h['asignacion_id'], h['salon_id'], h['dia'], h['hora_inicio'], h['hora_fin']) 
                       for h in lista_horarios]
            self.cursor.executemany(sql, valores)
            self.conexion.commit()
        except Exception as e:
            self.conexion.rollback()
            raise e