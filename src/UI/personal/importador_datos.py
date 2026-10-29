# -*- coding: utf-8 -*-
import os
import sys
import json
import sqlite3
import unicodedata
import datetime
import tkinter as tk
from tkinter import ttk, font, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk

from src.conexion import get_conexion, obtener_cursor
from src.clases.materia import materia
from src.clases.profesor import profesor
from src.clases.salon import salon
from src.clases.grupo import grupo
from src.UI.icon_manager import IconManager

class ImportadorDatosMixin:
    def exportar_datos_personal(self):
        carpeta_descargas = os.path.join(os.path.expanduser("~"), "Downloads")
        filepath = filedialog.asksaveasfilename(
            title="Exportar datos de Personal",
            defaultextension=".json",
            filetypes=[("Archivos JSON", "*.json")],
            initialdir=carpeta_descargas,
            initialfile="datos_personal.json"
        )
        if not filepath:
            return

        conn = get_conexion()
        if conn is None:
            messagebox.showerror("Error de conexión", "No se pudo conectar con la base de datos.")
            return

        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT profesor_id, no_cuenta, nombre, correo_institucional "
                "FROM profesores ORDER BY nombre"
            )
            profesores_rows = cur.fetchall()
            cur.execute(
                "SELECT profesor_id, dia, hora_inicio, hora_fin "
                "FROM profesor_disponibilidad ORDER BY id"
            )
            disponibilidad_por_profesor = {}
            for profesor_id, dia, hora_inicio, hora_fin in cur.fetchall():
                disponibilidad_por_profesor.setdefault(str(profesor_id), []).append({
                    "dia": dia,
                    "hora_inicio": str(hora_inicio),
                    "hora_fin": str(hora_fin)
                })

            profesores = [
                {
                    "profesor_id": profesor_id,
                    "no_cuenta": no_cuenta,
                    "nombre": nombre,
                    "correo_institucional": correo,
                    "disponibilidad": disponibilidad_por_profesor.get(str(profesor_id), [])
                }
                for profesor_id, no_cuenta, nombre, correo in profesores_rows
            ]

            cur.execute(
                "SELECT materia_id, nombre, horas_semana, semestre_id, tipo "
                "FROM materias ORDER BY materia_id"
            )
            materias = [
                {
                    "materia_id": materia_id,
                    "nombre": nombre,
                    "horas_semana": str(horas_semana),
                    "semestre_id": semestre_id,
                    "tipo": tipo
                }
                for materia_id, nombre, horas_semana, semestre_id, tipo in cur.fetchall()
            ]

            cur.execute("SELECT salon_id, capacidad, tipo FROM salones ORDER BY salon_id")
            salones = [
                {"salon_id": salon_id, "capacidad": capacidad, "tipo": tipo}
                for salon_id, capacidad, tipo in cur.fetchall()
            ]

            cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY grupo_id")
            grupos = [
                {"grupo_id": grupo_id, "nivel": nivel}
                for grupo_id, nivel in cur.fetchall()
            ]

            datos = {
                "formato": "saga_datos_personal",
                "version": 1,
                "profesores": profesores,
                "materias": materias,
                "salones": salones,
                "grupos": grupos
            }
            with open(filepath, "w", encoding="utf-8") as archivo:
                json.dump(datos, archivo, indent=2, ensure_ascii=False)
        except (OSError, sqlite3.Error) as err:
            messagebox.showerror("Error al exportar", f"No se pudieron exportar los datos: {err}")
            return
        finally:
            cur.close()
            conn.close()

        try:
            en_descargas = os.path.commonpath(
                [os.path.abspath(filepath), os.path.abspath(carpeta_descargas)]
            ) == os.path.abspath(carpeta_descargas)
        except ValueError:
            en_descargas = False

        if en_descargas:
            mensaje = f"El archivo se almacenó correctamente en la carpeta de Descargas:\n{filepath}"
        else:
            mensaje = f"El archivo se almacenó correctamente en:\n{filepath}"
        messagebox.showinfo("Exportación completa", mensaje)

    def _preguntar_coincidencia_catalogo(self, tipo, identificador, descripcion):
        dialogo = tk.Toplevel(self.master)
        dialogo.title("Coincidencia encontrada")
        dialogo.transient(self.master)
        dialogo.resizable(False, False)
        dialogo.grab_set()
        dialogo.resultado = None

        ttk.Label(
            dialogo,
            text=(
                f"Se encontró un registro de {tipo} que coincide con:\n"
                f"{identificador}\n\n{descripcion}\n\n"
                "¿Es el mismo registro? Sí lo actualizará sin crear un duplicado."
            ),
            justify="left",
            wraplength=420
        ).pack(padx=18, pady=(18, 12))

        botones = ttk.Frame(dialogo)
        botones.pack(fill="x", padx=12, pady=(0, 12))

        def cerrar(resultado):
            dialogo.resultado = resultado
            dialogo.destroy()

        ttk.Button(botones, text="Sí", command=lambda: cerrar("si")).pack(side="left", padx=4)
        ttk.Button(
            botones,
            text="No, crear otro",
            command=lambda: cerrar("no")
        ).pack(side="left", padx=4)
        ttk.Button(
            botones,
            text="Sí a todos",
            command=lambda: cerrar("si_todos")
        ).pack(side="right", padx=4)
        dialogo.protocol("WM_DELETE_WINDOW", lambda: cerrar("cancelar"))
        dialogo.bind("<Escape>", lambda event: cerrar("cancelar"))
        dialogo.wait_window()
        return dialogo.resultado

    @staticmethod
    def _nuevo_id_catalogo(base_id, existentes, max_length):
        base_id = str(base_id).strip()
        sufijo_num = 2
        while True:
            sufijo = f"_{sufijo_num}"
            candidato = f"{base_id[:max_length - len(sufijo)]}{sufijo}"
            if candidato not in existentes:
                return candidato
            sufijo_num += 1

    def importar_datos_personal(self):
        filepath = filedialog.askopenfilename(
            title="Importar datos de Personal",
            filetypes=[("Archivos JSON", "*.json")]
        )
        if not filepath:
            return

        try:
            with open(filepath, "r", encoding="utf-8") as archivo:
                datos = json.load(archivo)
        except (OSError, json.JSONDecodeError) as err:
            messagebox.showerror("Archivo inválido", f"No se pudo leer el archivo JSON: {err}")
            return

        if (
            not isinstance(datos, dict)
            or datos.get("formato") != "saga_datos_personal"
            or datos.get("version") != 1
        ):
            messagebox.showerror(
                "Formato no compatible",
                "Selecciona un archivo exportado desde la sección Personal."
            )
            return

        listas = {}
        for entidad in ("profesores", "materias", "salones", "grupos"):
            if entidad not in datos:
                messagebox.showerror(
                    "Archivo inválido",
                    f"El archivo no contiene la sección '{entidad}'."
                )
                return
            registros = datos[entidad]
            if not isinstance(registros, list) or any(not isinstance(registro, dict) for registro in registros):
                messagebox.showerror(
                    "Archivo inválido",
                    f"La sección '{entidad}' debe ser una lista de registros JSON."
                )
                return
            listas[entidad] = registros

        conn = get_conexion()
        if conn is None:
            messagebox.showerror("Error de conexión", "No se pudo conectar con la base de datos.")
            return

        cur = conn.cursor()
        conteos = {"profesores": 0, "materias": 0, "salones": 0, "grupos": 0}
        confirmar_todos = False
        try:
            cur.execute("SELECT profesor_id, no_cuenta, nombre FROM profesores")
            profesores_actuales = cur.fetchall()
            profesor_ids = {str(row[0]) for row in profesores_actuales}
            cur.execute("SELECT materia_id, nombre, semestre_id FROM materias")
            materias_actuales = cur.fetchall()
            materia_ids = {str(row[0]) for row in materias_actuales}
            cur.execute("SELECT salon_id FROM salones")
            salon_ids = {str(row[0]) for row in cur.fetchall()}
            cur.execute("SELECT grupo_id FROM grupos")
            grupo_ids = {str(row[0]) for row in cur.fetchall()}

            for registro in listas["profesores"]:
                cuenta = str(registro.get("no_cuenta") or "").strip()
                nombre = str(registro.get("nombre") or "").strip().upper()
                correo = str(registro.get("correo_institucional") or "").strip() or None
                profesor_id_archivo = str(registro.get("profesor_id") or "").strip().upper()
                disponibilidad = registro.get("disponibilidad", [])
                if not nombre or not isinstance(disponibilidad, list):
                    raise ValueError("Cada profesor debe incluir nombre y una lista de disponibilidad.")
                if len(nombre) > 255 or len(cuenta) > 20 or len(profesor_id_archivo) > 20:
                    raise ValueError(f"Los datos de identificación del profesor '{nombre}' exceden el tamaño permitido.")
                if correo and len(correo) > 255:
                    raise ValueError(f"El correo institucional de '{nombre}' excede 255 caracteres.")

                existente = None
                if profesor_id_archivo:
                    cur.execute("SELECT profesor_id FROM profesores WHERE profesor_id = %s", (profesor_id_archivo,))
                    existente = cur.fetchone()
                if not existente and cuenta:
                    cur.execute("SELECT profesor_id FROM profesores WHERE no_cuenta = %s LIMIT 1", (cuenta,))
                    existente = cur.fetchone()
                if not existente:
                    cur.execute("SELECT profesor_id FROM profesores WHERE nombre = %s LIMIT 1", (nombre,))
                    existente = cur.fetchone()

                mismo = False
                if existente:
                    if not confirmar_todos:
                        decision = self._preguntar_coincidencia_catalogo(
                            "profesor",
                            f"{cuenta or profesor_id_archivo or nombre} - {nombre}",
                            f"Correo institucional: {correo or '(vacío)'}"
                        )
                        if decision == "cancelar" or decision is None:
                            raise InterruptedError("Importación cancelada por el usuario.")
                        if decision == "si_todos":
                            confirmar_todos = True
                            mismo = True
                        else:
                            mismo = decision == "si"
                    else:
                        mismo = True

                if mismo:
                    nuevo_profesor_id = str(existente[0])
                    cur.execute(
                        "UPDATE profesores SET no_cuenta = %s, nombre = %s, correo_institucional = %s "
                        "WHERE profesor_id = %s",
                        (cuenta or None, nombre, correo, nuevo_profesor_id)
                    )
                    cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id = %s", (nuevo_profesor_id,))
                else:
                    nuevo_profesor_id = profesor_id_archivo
                    if not nuevo_profesor_id or nuevo_profesor_id in profesor_ids:
                        nuevo_profesor_id = _generar_profesor_id(cur)
                    cur.execute(
                        "INSERT INTO profesores "
                        "(profesor_id, no_cuenta, nombre, correo_institucional, disponible_inicio, "
                        "disponible_fin, dias_disponibles, en_linea, acude_toda_semana) "
                        "VALUES (%s, %s, %s, %s, '00:00:00', '00:00:00', '', 'NO', 'SI')",
                        (nuevo_profesor_id, cuenta or None, nombre, correo)
                    )
                    profesor_ids.add(nuevo_profesor_id)

                for periodo in disponibilidad:
                    if not isinstance(periodo, dict):
                        raise ValueError(f"La disponibilidad de '{nombre}' contiene un elemento inválido.")
                    dia = str(periodo.get("dia") or "").strip()
                    hora_inicio = str(periodo.get("hora_inicio") or "").strip()
                    hora_fin = str(periodo.get("hora_fin") or "").strip()
                    if not dia or not hora_inicio or not hora_fin:
                        raise ValueError(f"Un periodo de disponibilidad de '{nombre}' está incompleto.")
                    cur.execute(
                        "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin) "
                        "VALUES (%s, %s, %s, %s)",
                        (nuevo_profesor_id, dia, hora_inicio, hora_fin)
                    )
                conteos["profesores"] += 1

            for registro in listas["materias"]:
                materia_id = str(registro.get("materia_id") or "").strip().upper()
                nombre = str(registro.get("nombre") or "").strip().upper()
                horas = str(registro.get("horas_semana") or "").strip()
                semestre = registro.get("semestre_id")
                tipo = self._normalizar_tipo(registro.get("tipo"))
                if not materia_id or not nombre or not horas:
                    raise ValueError("Cada materia debe incluir clave, nombre y horas semanales.")
                if len(materia_id) > 20:
                    raise ValueError(f"La clave de materia '{materia_id}' excede 20 caracteres.")
                try:
                    horas_numero = float(horas)
                    if not math.isfinite(horas_numero) or horas_numero < 0:
                        raise ValueError
                    semestre = int(semestre) if semestre not in (None, "") else None
                except (TypeError, ValueError, OverflowError) as err:
                    raise ValueError(f"Los datos numéricos de la materia '{materia_id}' no son válidos.") from err
                if len(nombre) > 255 or len(tipo) > 50:
                    raise ValueError(f"Los datos de la materia '{materia_id}' exceden el tamaño permitido.")

                existente = None
                cur.execute("SELECT materia_id FROM materias WHERE materia_id = %s", (materia_id,))
                existente = cur.fetchone()
                if not existente:
                    cur.execute(
                        "SELECT materia_id FROM materias WHERE LOWER(nombre) = LOWER(%s) "
                        "AND semestre_id <=> %s LIMIT 1",
                        (nombre, semestre)
                    )
                    existente = cur.fetchone()

                mismo = False
                if existente:
                    if not confirmar_todos:
                        decision = self._preguntar_coincidencia_catalogo(
                            "materia",
                            materia_id,
                            f"{nombre} (semestre {semestre or 'sin semestre'})"
                        )
                        if decision == "cancelar" or decision is None:
                            raise InterruptedError("Importación cancelada por el usuario.")
                        if decision == "si_todos":
                            confirmar_todos = True
                            mismo = True
                        else:
                            mismo = decision == "si"
                    else:
                        mismo = True

                if mismo:
                    nuevo_materia_id = str(existente[0])
                    cur.execute(
                        "UPDATE materias SET nombre = %s, horas_semana = %s, semestre_id = %s, tipo = %s "
                        "WHERE materia_id = %s",
                        (nombre, horas, semestre, tipo, nuevo_materia_id)
                    )
                else:
                    nuevo_materia_id = materia_id
                    if nuevo_materia_id in materia_ids:
                        nuevo_materia_id = self._nuevo_id_catalogo(materia_id, materia_ids, 20)
                    cur.execute(
                        "INSERT INTO materias (materia_id, nombre, horas_semana, semestre_id, tipo) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (nuevo_materia_id, nombre, horas, semestre, tipo)
                    )
                    materia_ids.add(nuevo_materia_id)
                conteos["materias"] += 1

            for registro in listas["salones"]:
                salon_id = str(registro.get("salon_id") or "").strip().upper()
                capacidad = registro.get("capacidad", 0)
                tipo = self._normalizar_tipo(registro.get("tipo"))
                if not salon_id:
                    raise ValueError("Cada salón debe incluir un número de aula.")
                if capacidad is None:
                    capacidad = 0
                if len(salon_id) > 50:
                    raise ValueError(f"El identificador del salón '{salon_id}' excede 50 caracteres.")
                try:
                    capacidad = int(capacidad)
                except (TypeError, ValueError, OverflowError) as err:
                    raise ValueError(f"La capacidad del salón '{salon_id}' no es válida.") from err
                if capacidad < 0:
                    raise ValueError(f"La capacidad del salón '{salon_id}' no puede ser negativa.")
                if len(tipo) > 50:
                    raise ValueError(f"El tipo del salón '{salon_id}' excede 50 caracteres.")

                cur.execute("SELECT salon_id FROM salones WHERE salon_id = %s", (salon_id,))
                existente = cur.fetchone()
                mismo = False
                if existente:
                    if not confirmar_todos:
                        decision = self._preguntar_coincidencia_catalogo(
                            "salón", salon_id, f"Capacidad: {capacidad}; tipo: {tipo}"
                        )
                        if decision == "cancelar" or decision is None:
                            raise InterruptedError("Importación cancelada por el usuario.")
                        if decision == "si_todos":
                            confirmar_todos = True
                            mismo = True
                        else:
                            mismo = decision == "si"
                    else:
                        mismo = True

                if mismo:
                    nuevo_salon_id = str(existente[0])
                    cur.execute(
                        "UPDATE salones SET capacidad = %s, tipo = %s WHERE salon_id = %s",
                        (capacidad, tipo, nuevo_salon_id)
                    )
                else:
                    nuevo_salon_id = salon_id
                    if nuevo_salon_id in salon_ids:
                        nuevo_salon_id = self._nuevo_id_catalogo(salon_id, salon_ids, 50)
                    cur.execute(
                        "INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, %s, %s)",
                        (nuevo_salon_id, capacidad, tipo)
                    )
                    salon_ids.add(nuevo_salon_id)
                conteos["salones"] += 1

            for registro in listas["grupos"]:
                grupo_id = str(registro.get("grupo_id") or "").strip().upper()
                nivel = registro.get("nivel")
                if not grupo_id:
                    raise ValueError("Cada grupo debe incluir un identificador.")
                if len(grupo_id) > 20:
                    raise ValueError(f"El identificador del grupo '{grupo_id}' excede 20 caracteres.")
                if nivel not in (None, ""):
                    try:
                        nivel = int(nivel)
                    except (TypeError, ValueError, OverflowError) as err:
                        raise ValueError(f"El semestre del grupo '{grupo_id}' no es válido.") from err
                else:
                    nivel = None

                cur.execute("SELECT grupo_id FROM grupos WHERE grupo_id = %s", (grupo_id,))
                existente = cur.fetchone()
                mismo = False
                if existente:
                    if not confirmar_todos:
                        decision = self._preguntar_coincidencia_catalogo(
                            "grupo", grupo_id, f"Semestre: {nivel}"
                        )
                        if decision == "cancelar" or decision is None:
                            raise InterruptedError("Importación cancelada por el usuario.")
                        if decision == "si_todos":
                            confirmar_todos = True
                            mismo = True
                        else:
                            mismo = decision == "si"
                    else:
                        mismo = True

                if mismo:
                    nuevo_grupo_id = str(existente[0])
                    cur.execute(
                        "UPDATE grupos SET nivel = %s WHERE grupo_id = %s",
                        (nivel, nuevo_grupo_id)
                    )
                else:
                    nuevo_grupo_id = grupo_id
                    if nuevo_grupo_id in grupo_ids:
                        nuevo_grupo_id = self._nuevo_id_catalogo(grupo_id, grupo_ids, 20)
                    cur.execute(
                        "INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)",
                        (nuevo_grupo_id, nivel)
                    )
                    grupo_ids.add(nuevo_grupo_id)
                conteos["grupos"] += 1

            conn.commit()
        except InterruptedError:
            conn.rollback()
            return
        except (ValueError, sqlite3.Error) as err:
            conn.rollback()
            messagebox.showerror("Error al importar", f"No se importaron los datos: {err}")
            return
        finally:
            cur.close()
            conn.close()

        self._refresh_all()
        resumen = "\n".join(f"{tipo.title()}: {cantidad}" for tipo, cantidad in conteos.items())
        messagebox.showinfo("Importación completa", f"Datos procesados correctamente:\n\n{resumen}")
