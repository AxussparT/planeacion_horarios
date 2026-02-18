import mysql.connector
import datetime # <--- CAMBIO: Importamos el módulo completo para evitar confusiones

class GeneradorHorarios:
    def __init__(self, conexion):
        self.conexion = conexion
        self.cursor = self.conexion.cursor(dictionary=True)
        
        # CONFIGURACIÓN: 7:00 AM es el slot 0. Bloques de 30 min.
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
        """Convierte datetime.timedelta o datetime.time a índice de slot"""
        
        # CAMBIO: Usamos datetime.timedelta explícitamente
        if isinstance(hora_time, datetime.timedelta):
            total_minutos = hora_time.seconds // 60
            horas = total_minutos // 60
            minutos = total_minutos % 60
        # CAMBIO: Verificamos si es datetime.time (algunas BD lo devuelven así)
        elif isinstance(hora_time, datetime.time):
            horas = hora_time.hour
            minutos = hora_time.minute
        else:
            # Si llega aquí, intentamos tratarlo como objeto datetime.datetime
            try:
                horas = hora_time.hour
                minutos = hora_time.minute
            except AttributeError:
                print(f"Error de tipo de dato en hora: {type(hora_time)}")
                return 0
            
        slot = (horas - self.HORA_INICIO_CLASES) * 2
        if minutos >= 30:
            slot += 1
        return int(slot)

    def _slot_a_hora(self, slot):
        """Convierte un índice de slot de vuelta a texto"""
        minutos_total = slot * 30
        horas = self.HORA_INICIO_CLASES + (minutos_total // 60)
        minutos = minutos_total % 60
        return f"{horas:02d}:{minutos:02d}:00"

    def cargar_datos(self):
        # 1. Asignaciones pendientes
        # CORRECCIÓN: Cambiamos a.id_asignacion por a.asignacion_id
        sql_asignaciones = """
            SELECT a.asignacion_id, a.profesor_id, a.materia_id, a.grupo_id, 
                   p.disponible_inicio, p.disponible_fin, p.dias_disponibles
            FROM asignaciones a
            JOIN profesores p ON a.profesor_id = p.profesor_id
        """
        self.cursor.execute(sql_asignaciones)
        self.asignaciones = self.cursor.fetchall()

        # 2. Salones
        self.cursor.execute("SELECT salon_id FROM salones")
        self.salones = [row['salon_id'] for row in self.cursor.fetchall()]

    def es_posible_asignar(self, asignacion, dia, slot_inicio, duracion_bloques, salon_id):
        prof_id = asignacion['profesor_id']
        grupo_id = asignacion['grupo_id']

        if slot_inicio + duracion_bloques > self.SLOTS_DIARIOS:
            return False

        # Validación segura de horas
        if not asignacion['disponible_inicio'] or not asignacion['disponible_fin']:
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

    def ejecutar(self):
        self.cargar_datos()
        self._limpiar_matrices()
        
        horarios_generados = []
        dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        
        print(f"--- Encontradas {len(self.asignaciones)} asignaciones para procesar ---")

        for asignacion in self.asignaciones:
            asignado = False
            bloques_necesarios = 4 
            
            # DEBUG: Imprimir qué ID se está procesando
            # CORRECCIÓN: Usamos la clave 'asignacion_id'
            print(f"Procesando ID: {asignacion['asignacion_id']} - Prof: {asignacion['profesor_id']}")

            for dia in dias_semana:
                if asignado: break
                for salon in self.salones:
                    if asignado: break
                    for slot in range(self.SLOTS_DIARIOS):
                        if self.es_posible_asignar(asignacion, dia, slot, bloques_necesarios, salon):
                            self.registrar_ocupacion(asignacion, dia, slot, bloques_necesarios, salon)
                            
                            horario = {
                                # CORRECCIÓN IMPORTANTE AQUÍ ABAJO:
                                "asignacion_id": asignacion['asignacion_id'], 
                                "salon_id": salon,
                                "dia": dia,
                                "hora_inicio": self._slot_a_hora(slot),
                                "hora_fin": self._slot_a_hora(slot + bloques_necesarios)
                            }
                            horarios_generados.append(horario)
                            asignado = True
                            break
            
            if not asignado:
                print(f"ALERTA: No se pudo asignar ID {asignacion['asignacion_id']}")

        self.guardar_en_bd(horarios_generados)
        return len(horarios_generados)

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