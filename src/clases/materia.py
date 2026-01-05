from src.conexion import get_conexion
from tkinter import messagebox
import mysql.connector
from .Validar_materia import validar_y_registrar_materia # Importa la función de validación

class materia:
    def __init__(self, clave, nombre, horas_semana, semestre):
        self.clave = clave
        self.nombre = nombre
        
        # Variables principales de la materia
        self.horas_semana = horas_semana
        self.semestre = semestre
        
        print(f"Datos de materia guardados en el objeto: {self.nombre}")
        
        # Inicia el procesamiento de la lógica de negocio
        self.procesar_datos()

    def procesar_datos(self):
        """
        Transfiere los datos del objeto a la función de validación y registro de la BD.
        """
        print("Enviando datos a la función de validación...")
        
        # Llama a la función externa para manejar la lógica y la DB
        exito = validar_y_registrar_materia(
            self.clave, 
            self.nombre, 
            self.horas_semana, 
            self.semestre
        ) 
        if exito:
            print("Registro/Actualización de materia completado con éxito.")
        else:
            print("Fallo en el registro/actualización de materia.")
        return exito