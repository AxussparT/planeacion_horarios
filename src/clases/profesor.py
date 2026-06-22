from src.conexion import get_conexion
from tkinter import messagebox
import mysql.connector
from .validacion_bd import validar_y_registrar_profesor


class profesor:
    def __init__(self, no_cuenta, nombre_completo, periodos):
        self.no_cuenta = no_cuenta
        self.nombre_completo = nombre_completo
        self.periodos = periodos

        exito = validar_y_registrar_profesor(
            self.no_cuenta,
            self.nombre_completo,
            self.periodos
        )
        return exito
