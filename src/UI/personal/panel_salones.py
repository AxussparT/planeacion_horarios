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

class PanelSalonesMixin:
    def evento_Salones(self):
        self.master.update_idletasks()
        aula = self.entry_num_aula.get().strip().upper()
        cap = self.entry_capacidad_aula.get().strip()
        tipo = self._db_tipo_materia_salon(self.combo_tipo.get())
        if not aula or len(aula) > 4:
            messagebox.showwarning("Aviso", "El número de aula es obligatorio y debe tener hasta 4 caracteres.")
            return
        if not cap.isascii() or not cap.isdigit() or len(cap) > 3:
            messagebox.showwarning("Aviso", "La capacidad debe ser un número entero de hasta 3 dígitos.")
            return
        if not tipo or len(tipo) > 50:
            messagebox.showwarning("Aviso", "Selecciona un tipo de salón válido.")
            return
        registro = salon(numero_aula=aula, capacidad=cap, tipo=tipo)
        if registro.exito:
            self.entry_num_aula.delete(0, tk.END)
            self.entry_capacidad_aula.delete(0, tk.END)
            self.combo_tipo.set("")
            self._refresh_all()

    def mostrar_datos_salones(self):
        conn = get_conexion()
        cur = conn.cursor()
        cur.execute("SELECT salon_id, capacidad, tipo FROM salones")
        res = cur.fetchall()
        conn.close()
        self.tabla_salones.delete(*self.tabla_salones.get_children())
        for r in res:
            if r[0].upper().startswith("MEDIACION_TECNOLOGICA"):
                continue
            fila = list(r)
            if len(fila) > 2:
                fila[2] = self._ui_tipo_materia_salon(fila[2])
            self.tabla_salones.insert("", "end", values=fila)

    def eliminar_salon(self):
        aula_id = self.entry_num_aula.get().strip()
        if not aula_id:
            return
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar el aula {aula_id}?\nSe eliminarán también sus horarios asignados."):
            from src.conexion import obtener_cursor
            exito = False
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM horarios WHERE salon_id = %s", (aula_id,))
                    cur.execute("DELETE FROM salones WHERE salon_id = %s", (aula_id,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self.limpiar_campos_salon()
                self._refresh_all()
                messagebox.showinfo("Éxito", "Salón eliminado correctamente.")

    def limpiar_campos_salon(self):
        self.entry_num_aula.delete(0, tk.END)
        self.entry_capacidad_aula.delete(0, tk.END)
        self.combo_tipo.set("")

    def cargar_salon_seleccionado(self, event):
        item = self.tabla_salones.focus()
        if not item:
            return
        v = self.tabla_salones.item(item, "values")
        self.limpiar_campos_salon()
        self.entry_num_aula.insert(0, v[0])
        self.entry_capacidad_aula.insert(0, v[1])
        if len(v) > 2:
            self.combo_tipo.set(self._ui_tipo_materia_salon(v[2]))
