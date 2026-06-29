import json
import os
import sys
import mysql.connector
from tkinter import messagebox
from contextlib import contextmanager

_CONFIG = None

def _ruta_usuario(relative_path):
    try:
        base = os.path.dirname(os.path.abspath(sys.executable))
    except Exception:
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base, relative_path)

def _cargar_config():
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    ruta = _ruta_usuario("config.json")
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            _CONFIG = json.load(f)
    else:
        _CONFIG = {
            "host": "localhost",
            "port": "3306",
            "user": "root",
            "password": "123456",
            "database": "bd_seso"
        }
    return _CONFIG

def guardar_config(host, port, user, password, database):
    cfg = {"host": host, "port": port, "user": user, "password": password, "database": database}
    ruta = _ruta_usuario("config.json")
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        global _CONFIG
        _CONFIG = cfg
        return True
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo guardar la configuración:\n{e}")
        return False

def get_conexion():
    try:
        cfg = _cargar_config()
        conexion = mysql.connector.connect(
            host=cfg.get("host", "localhost"),
            user=cfg.get("user", "root"),
            password=cfg.get("password", "123456"),
            database=cfg.get("database", "bd_seso"),
            port=cfg.get("port", "3306")
        )
        return conexion
    except mysql.connector.Error as err:
        if _CONFIG is not None:
            messagebox.showerror("Error de Conexión", f"No se pudo conectar a la base de datos:\n{err}")
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
