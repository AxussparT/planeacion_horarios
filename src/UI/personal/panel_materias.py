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

class PanelMateriasMixin:
    def cargar_materia_seleccionada(self, event):
        item = self.tabla_materias.focus()
        if not item:
            return
        v = self.tabla_materias.item(item, "values")
        self.limpiar_campos_materia()
        self.entry_materia_clave.insert(0, v[0])
        self.entry_materia_nom.insert(0, v[1])
        self.entry_materia_horas.insert(0, v[2])
        self.entry_materia_semestre.insert(0, v[3])
        if len(v) > 4:
            self.combo_preferencia.set(self._ui_tipo_materia_salon(v[4]))

    def evento_materias(self):
        self.master.update_idletasks()
        c = self.entry_materia_clave.get().strip().upper()
        n = self.entry_materia_nom.get().strip().upper()
        h = self.entry_materia_horas.get().strip()
        s = self.entry_materia_semestre.get().strip()
        t = self._db_tipo_materia_salon(self.combo_preferencia.get())
        if not c or len(c) > 20 or not n or len(n) > 255:
            messagebox.showwarning("Aviso", "La clave es obligatoria (máximo 20 caracteres) y el nombre (máximo 255).")
            return
        if not h.isascii() or not h.isdigit() or len(h) > 2:
            messagebox.showwarning("Aviso", "Las horas semanales deben ser un número entero de hasta 2 dígitos.")
            return
        if s and (not s.isascii() or not s.isdigit() or len(s) > 2):
            messagebox.showwarning("Aviso", "El semestre debe ser un número entero de hasta 2 dígitos.")
            return
        if not t or len(t) > 50:
            messagebox.showwarning("Aviso", "Selecciona un tipo de materia válido.")
            return
        registro = materia(c, n, h, s, t)
        if registro.exito:
            for e in [self.entry_materia_clave, self.entry_materia_nom, self.entry_materia_horas, self.entry_materia_semestre]:
                e.delete(0, tk.END)
            self._refresh_all()

    def mostrar_datos_materias(self):
        self.cache_materias.clear()
        conn = get_conexion()
        cur = conn.cursor()
        cur.execute("SELECT materia_id, nombre, horas_semana, semestre_id, tipo FROM materias")
        self.cache_materias = cur.fetchall()
        conn.close()
        self.refrescar_tabla_mat(self.cache_materias)

    def refrescar_tabla_mat(self, datos):
        self.tabla_materias.delete(*self.tabla_materias.get_children())
        for d in datos:
            fila = list(d)
            if len(fila) > 4:
                fila[4] = self._ui_tipo_materia_salon(fila[4])
            self.tabla_materias.insert("", "end", values=fila)

    def filtrar_materias(self):
        t = self.sv_busqueda_mat.get().lower()
        s = self.sv_filtro_semestre.get()
        f = []
        for m in self.cache_materias:
            coincide_texto = (t in str(m[0]).lower() or t in m[1].lower())
            coincide_sem = (s == "Todos" or str(m[3]) == s)
            if coincide_texto and coincide_sem:
                f.append(m)
        self.refrescar_tabla_mat(f)

    def limpiar_campos_materia(self):
        self.entry_materia_clave.delete(0, tk.END)
        self.entry_materia_nom.delete(0, tk.END)
        self.entry_materia_horas.delete(0, tk.END)
        self.entry_materia_semestre.delete(0, tk.END)
        self.combo_preferencia.set("")

    def eliminar_materia(self):
        materia_id = self.entry_materia_clave.get().strip()
        if not materia_id:
            return
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar la materia con clave '{materia_id}'?"):
            from src.conexion import obtener_cursor
            exito = False
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM asignaciones WHERE materia_id = %s", (materia_id,))
                    cur.execute("DELETE FROM materias WHERE materia_id = %s", (materia_id,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self.limpiar_campos_materia()
                self._refresh_all()
                messagebox.showinfo("Éxito", "Materia eliminada correctamente.")
