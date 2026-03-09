from src.conexion import get_conexion
from tkinter import messagebox
import mysql.connector
from .Validar_materia import validar_y_registrar_materia 

class materia:
    # Agregamos 'tipo' al constructor
    def __init__(self, clave, nombre, horas_semana, semestre, tipo):
        self.clave = clave
        self.nombre = nombre
        self.horas_semana = horas_semana
        self.semestre = semestre
        self.tipo = tipo  # <--- Nueva variable: "Normal", "Tecnológica" o "Laboratorio"
        
        print(f"Datos de materia guardados en el objeto: {self.nombre} (Tipo: {self.tipo})")
        
        # Inicia el procesamiento de la lógica de negocio
        self.procesar_datos()

    def procesar_datos(self):
        """
        Transfiere los datos del objeto a la función de validación y registro de la BD.
        """
        print("Enviando datos a la función de validación...")
        
        # Agregamos self.tipo a la llamada de la función
        exito = validar_y_registrar_materia(
            self.clave, 
            self.nombre, 
            self.horas_semana, 
            self.semestre,
            self.tipo  # <--- Pasamos el nuevo dato
        ) 
        if exito:
            print("Registro/Actualización de materia completado con éxito.")
        else:
            print("Fallo en el registro/actualización de materia.")
        return exito