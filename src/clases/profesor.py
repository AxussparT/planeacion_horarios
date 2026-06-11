from src.conexion import get_conexion
from tkinter import messagebox
import mysql.connector
from .validacion_bd import validar_y_registrar_profesor


class profesor:
    def __init__(self, cuenta, nombre_completo, periodos, linea):
        self.cuenta = cuenta
        self.nombre_completo = nombre_completo
        self.periodos = periodos
        self.linea = linea

        exito = validar_y_registrar_profesor(
            self.cuenta,
            self.nombre_completo,
            self.periodos,
            self.linea
        )
        return exito
