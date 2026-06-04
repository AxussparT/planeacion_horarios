import mysql.connector
from tkinter import messagebox
from contextlib import contextmanager

def get_conexion():
    try:
        conexion = mysql.connector.connect(
            host="localhost",
            user="root",
            password="123456",
            database="bd_seso",
            port='3306'
        )
        return conexion
    except mysql.connector.Error as err:
        messagebox.showerror("Error de Conexión", f"No se pudo conectar a la base de datos: {err}")
        return None

@contextmanager
def obtener_cursor():
    conn = get_conexion()
    if conn is None:
        yield None
        return
    cursor = conn.cursor()
    try:
        yield cursor, conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn.is_connected():
            conn.close()

@contextmanager
def obtener_cursor_dict():
    conn = get_conexion()
    if conn is None:
        yield None
        return
    cursor = conn.cursor(dictionary=True)
    try:
        yield cursor, conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn.is_connected():
            conn.close()