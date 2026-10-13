import sqlite3

from src.conexion import get_conexion, get_ruta_base_datos


def main():
    conn = get_conexion()
    if conn is None:
        print("No se pudo abrir la base de datos SQLite.")
        return 1

    try:
        print(f"Base de datos: {get_ruta_base_datos()}")
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(horarios)")
        print("\n=== Columnas de horarios ===")
        for columna in cursor.fetchall():
            print(f"  {columna['name']}: {columna['type']}")

        cursor.execute("SELECT COUNT(*) FROM horarios")
        print(f"\nRegistros en horarios: {cursor.fetchone()[0]}")

        cursor.execute("PRAGMA foreign_key_check")
        violaciones = cursor.fetchall()
        if violaciones:
            print(f"Referencias inválidas: {len(violaciones)}")
            for violacion in violaciones[:10]:
                print(f"  {tuple(violacion)}")
        else:
            print("Integridad de claves foráneas: correcta")
    except sqlite3.Error as err:
        print(f"Error al diagnosticar la base SQLite: {err}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
