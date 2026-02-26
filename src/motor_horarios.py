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

    def _limpiar_matrices(self):
        self.ocupacion_salones = {}
        self.ocupacion_profesores = {}
        self.ocupacion_grupos = {}

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
        # CAMBIO: Añadimos el JOIN con materias para traer m.horas_semana
        sql_asignaciones = """
            SELECT a.asignacion_id, a.profesor_id, a.materia_id, a.grupo_id, 
                   p.disponible_inicio, p.disponible_fin, p.dias_disponibles,
                   IFNULL(m.horas_semana, 4) as horas_semana -- Por si viene NULL, asumimos 4
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

    def intentar_asignar_bloque(self, asignacion, dia, duracion_bloques, salon, horarios_generados):
        """Intenta colocar un bloque de horas en un día y salón específicos"""
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
                return True # Éxito
        return False

    def ejecutar(self):
        self.cargar_datos()
        self._limpiar_matrices()
        
        horarios_generados = []
        
        print(f"--- Encontradas {len(self.asignaciones)} asignaciones para procesar ---")

        for asignacion in self.asignaciones:
            # 1 hora = 2 bloques de 30 mins
            horas_totales = float(asignacion['horas_semana'])
            bloques_totales = int(horas_totales * 2) 
            
            # ESTRATEGIAS DE DIVISIÓN
            if bloques_totales >= 6:
                # Partimos las horas a la mitad. Ej: 5 horas -> 3h y 2h.
                '''
                horas_dia1 = math.ceil(horas_totales / 2)
                horas_dia2 = horas_totales - horas_dia1
                '''
                bloques_dia1 = math.ceil(bloques_totales/2)
                bloques_dia2 = bloques_totales-bloques_dia1
                
                estrategias = [
                    # Estrategia 1: Lunes y Miércoles
                    [("Lunes", bloques_dia1), ("Miércoles", bloques_dia2)],
                    # Estrategia 2: Martes y Jueves
                    [("Martes", bloques_dia1), ("Jueves", bloques_dia2)],
                    # Estrategia 3: Todo junto en un solo día (Fallback)
                    [("Viernes", bloques_totales)],
                    [("Lunes", bloques_totales)]
                ]
            else:
                # Materias de 1 o 2 horas se asignan juntas un solo día
                estrategias = [
                    [("Lunes", bloques_totales)], [("Martes", bloques_totales)], 
                    [("Miércoles", bloques_totales)], [("Jueves", bloques_totales)], [("Viernes", bloques_totales)]
                ]

            asignado_completamente = False
            
            # Buscar salón disponible para aplicar la estrategia
            for salon in self.salones:
                if asignado_completamente: break
                
                for estrategia in estrategias:
                    exito_estrategia = True
                    horarios_temporales = []
                    
                    # Intentar acomodar todas las partes de esta estrategia
                    for dia, bloques_requeridos in estrategia:
                        exito_bloque = self.intentar_asignar_bloque(asignacion, dia, bloques_requeridos, salon, horarios_temporales)
                        if not exito_bloque:
                            exito_estrategia = False
                            break # Falla un día de la estrategia, se cancela esta estrategia completa
                    
                    if exito_estrategia:
                        # La estrategia funcionó, guardamos los horarios
                        horarios_generados.extend(horarios_temporales)
                        asignado_completamente = True
                        break 
                    else:
                        # Rollback: Des-ocupar si la estrategia falló a medias (ej. pudo el Lunes pero no el Miércoles)
                        for ht in horarios_temporales:
                            self._deshacer_ocupacion(asignacion, ht['dia'], self._hora_a_slot(datetime.datetime.strptime(ht['hora_inicio'], "%H:%M:%S").time()), ht['salon_id'], bloques_requeridos)

            if not asignado_completamente:
                print(f"ALERTA: No se pudo asignar ID {asignacion['asignacion_id']} ({horas_totales} hrs)")

        self.guardar_en_bd(horarios_generados)
        return len(horarios_generados)

    def _deshacer_ocupacion(self, asignacion, dia, slot_inicio, salon_id, duracion_bloques):
        """Función auxiliar para limpiar la ocupación si una estrategia falla a la mitad"""
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']
        for i in range(duracion_bloques):
            slot = slot_inicio + i
            if (dia, salon_id, slot) in self.ocupacion_salones: del self.ocupacion_salones[(dia, salon_id, slot)]
            if (dia, prof_id, slot) in self.ocupacion_profesores: del self.ocupacion_profesores[(dia, prof_id, slot)]
            if (dia, grupo_id, slot) in self.ocupacion_grupos: del self.ocupacion_grupos[(dia, grupo_id, slot)]

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