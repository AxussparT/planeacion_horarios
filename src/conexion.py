import datetime
import decimal
import os
import re
import sqlite3
import threading
from contextlib import contextmanager

DatabaseError = sqlite3.Error
_ESQUEMA_INICIALIZADO = False
_BLOQUEO_ESQUEMA = threading.Lock()

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS profesores (
    profesor_id TEXT PRIMARY KEY,
    no_cuenta TEXT,
    nombre TEXT NOT NULL,
    correo_institucional TEXT DEFAULT NULL,
    disponible_inicio TIME DEFAULT NULL,
    disponible_fin TIME DEFAULT NULL,
    dias_disponibles TEXT DEFAULT NULL,
    en_linea TEXT DEFAULT 'NO'
);

CREATE TABLE IF NOT EXISTS materias (
    materia_id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    horas_semana NUMERIC NOT NULL DEFAULT 0,
    semestre_id INTEGER DEFAULT NULL,
    tipo TEXT NOT NULL DEFAULT 'NORMAL'
);

CREATE TABLE IF NOT EXISTS grupos (
    grupo_id TEXT PRIMARY KEY,
    nivel INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS grupo_materias (
    grupo_id TEXT NOT NULL,
    materia_id TEXT NOT NULL,
    PRIMARY KEY (grupo_id, materia_id),
    FOREIGN KEY (grupo_id) REFERENCES grupos(grupo_id) ON DELETE CASCADE,
    FOREIGN KEY (materia_id) REFERENCES materias(materia_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_grupo_materias_grupo ON grupo_materias(grupo_id);
CREATE INDEX IF NOT EXISTS idx_grupo_materias_materia ON grupo_materias(materia_id);

CREATE TABLE IF NOT EXISTS salones (
    salon_id TEXT PRIMARY KEY,
    capacidad INTEGER NOT NULL DEFAULT 0,
    tipo TEXT NOT NULL DEFAULT 'NORMAL'
);

CREATE TABLE IF NOT EXISTS semestres (
    id_semestre INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profesor_disponibilidad (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profesor_id TEXT NOT NULL,
    dia TEXT NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    modalidad TEXT NOT NULL DEFAULT 'Presencial',
    FOREIGN KEY (profesor_id) REFERENCES profesores(profesor_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_profesor_disponibilidad_profesor
    ON profesor_disponibilidad(profesor_id);

CREATE TABLE IF NOT EXISTS asignaciones (
    asignacion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    profesor_id TEXT NOT NULL,
    materia_id TEXT NOT NULL,
    grupo_id TEXT NOT NULL,
    periodo TEXT NOT NULL DEFAULT 'A',
    hora_inicio TIME DEFAULT NULL,
    hora_fin TIME DEFAULT NULL,
    dias TEXT DEFAULT NULL,
    modalidad TEXT NOT NULL DEFAULT 'Presencial',
    estado TEXT DEFAULT 'pendiente',
    FOREIGN KEY (profesor_id) REFERENCES profesores(profesor_id) ON DELETE CASCADE,
    FOREIGN KEY (materia_id) REFERENCES materias(materia_id) ON DELETE CASCADE,
    FOREIGN KEY (grupo_id) REFERENCES grupos(grupo_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_asignaciones_profesor
    ON asignaciones(profesor_id);
CREATE INDEX IF NOT EXISTS idx_asignaciones_materia_grupo
    ON asignaciones(materia_id, grupo_id);

CREATE TABLE IF NOT EXISTS horarios (
    horario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asignacion_id INTEGER NOT NULL,
    salon_id TEXT NOT NULL,
    dia TEXT NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    FOREIGN KEY (asignacion_id) REFERENCES asignaciones(asignacion_id) ON DELETE CASCADE,
    FOREIGN KEY (salon_id) REFERENCES salones(salon_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_horarios_asignacion ON horarios(asignacion_id);
CREATE INDEX IF NOT EXISTS idx_horarios_salon_dia ON horarios(salon_id, dia);
"""

_SEMESTRES_INICIALES = (
    (1, "Primer Semestre"),
    (2, "Segundo Semestre"),
    (3, "Tercer Semestre"),
    (4, "Cuarto Semestre"),
    (5, "Quinto Semestre"),
    (6, "Sexto Semestre"),
    (7, "Séptimo Semestre"),
    (8, "Octavo Semestre"),
    (9, "Noveno Semestre"),
    (10, "Décimo Semestre"),
)


def _ruta_base_datos():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        directorio = os.path.join(local_app_data, "SAGA")
    else:
        directorio = os.path.join(os.path.expanduser("~"), ".local", "share", "SAGA")
    os.makedirs(directorio, exist_ok=True)
    return os.path.join(directorio, "saga.sqlite3")


def get_ruta_base_datos():
    return _ruta_base_datos()


def _a_texto_sqlite(valor):
    if isinstance(valor, datetime.timedelta):
        total_segundos = int(valor.total_seconds())
        signo = "-" if total_segundos < 0 else ""
        horas, resto = divmod(abs(total_segundos), 3600)
        minutos, segundos = divmod(resto, 60)
        return f"{signo}{horas:02d}:{minutos:02d}:{segundos:02d}"
    if isinstance(valor, datetime.time):
        return valor.strftime("%H:%M:%S")
    return valor


def _desde_hora_sqlite(valor):
    texto = valor.decode("utf-8")
    partes = texto.split(":")
    if len(partes) < 2:
        raise ValueError(f"Hora SQLite inválida: {texto}")
    horas = int(partes[0])
    minutos = int(partes[1])
    segundos = float(partes[2]) if len(partes) > 2 else 0
    return datetime.timedelta(
        hours=horas,
        minutes=minutos,
        seconds=segundos
    )


sqlite3.register_adapter(datetime.timedelta, _a_texto_sqlite)
sqlite3.register_adapter(datetime.time, _a_texto_sqlite)
sqlite3.register_adapter(decimal.Decimal, str)
sqlite3.register_converter("TIME", _desde_hora_sqlite)


def _adaptar_consulta(sql):
    consulta = sql.strip()
    truncar = re.fullmatch(r"TRUNCATE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)", consulta, re.IGNORECASE)
    if truncar:
        tabla = truncar.group(1)
        return f"DELETE FROM {tabla}", tabla

    consulta = re.sub(r"<=>", "IS", consulta)
    consulta = re.sub(r"\bINSERT\s+IGNORE\b", "INSERT OR IGNORE", consulta, flags=re.IGNORECASE)
    consulta = re.sub(r"%s", "?", consulta)
    return consulta, None


class _CursorAdaptado:
    def __init__(self, cursor, como_diccionario=False):
        self._cursor = cursor
        self._como_diccionario = como_diccionario

    def execute(self, sql, parametros=()):
        consulta, tabla_truncada = _adaptar_consulta(sql)
        self._cursor.execute(consulta, tuple(_a_texto_sqlite(p) for p in parametros))
        if tabla_truncada:
            try:
                self._cursor.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tabla_truncada,))
            except sqlite3.OperationalError:
                pass
        return self

    def executemany(self, sql, parametros):
        consulta, tabla_truncada = _adaptar_consulta(sql)
        if tabla_truncada:
            raise sqlite3.ProgrammingError("TRUNCATE TABLE no admite ejecutarse en lote.")
        parametros_adaptados = (
            tuple(_a_texto_sqlite(p) for p in fila) for fila in parametros
        )
        self._cursor.executemany(consulta, parametros_adaptados)
        return self

    def _convertir_fila(self, fila):
        if fila is None:
            return fila
        if self._como_diccionario:
            return dict(fila)
        return tuple(fila)

    def fetchone(self):
        return self._convertir_fila(self._cursor.fetchone())

    def fetchall(self):
        filas = self._cursor.fetchall()
        if self._como_diccionario:
            return [dict(fila) for fila in filas]
        return [tuple(fila) for fila in filas]

    def fetchmany(self, size=None):
        filas = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        if self._como_diccionario:
            return [dict(fila) for fila in filas]
        return [tuple(fila) for fila in filas]

    def close(self):
        self._cursor.close()

    def __getattr__(self, nombre):
        return getattr(self._cursor, nombre)


class _ConexionSQLite(sqlite3.Connection):
    def cursor(self, dictionary=False):
        cursor = super().cursor()
        return _CursorAdaptado(cursor, como_diccionario=dictionary)

    def is_connected(self):
        try:
            self.execute("SELECT 1")
            return True
        except sqlite3.ProgrammingError:
            return False


def _inicializar_esquema(conn):
    global _ESQUEMA_INICIALIZADO
    if _ESQUEMA_INICIALIZADO:
        return
    with _BLOQUEO_ESQUEMA:
        if _ESQUEMA_INICIALIZADO:
            return
        _crear_esquema(conn)
        _ESQUEMA_INICIALIZADO = True


def _crear_esquema(conn):
    conn.executescript(_ESQUEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO semestres (id_semestre, nombre) VALUES (?, ?)",
        _SEMESTRES_INICIALES
    )
    conn.commit()


def get_conexion():
    try:
        ruta = _ruta_base_datos()
        conexion = sqlite3.connect(
            ruta,
            timeout=30,
            detect_types=sqlite3.PARSE_DECLTYPES,
            factory=_ConexionSQLite
        )
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute("PRAGMA busy_timeout = 30000")
        _inicializar_esquema(conexion)
        return conexion
    except sqlite3.Error as err:
        print(f"Error abriendo la base de datos SQLite: {err}")
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
        cursor.close()
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
        cursor.close()
        conn.close()
