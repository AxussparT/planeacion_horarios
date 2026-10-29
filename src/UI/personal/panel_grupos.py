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

class PanelGruposMixin:
    def _on_cambio_semestre_grupo(self, materias_preseleccionadas=None):
        sem_str = self.entry_grupo_nivel.get().strip()
        for w in self.frame_mat_grp_checks.winfo_children():
            w.destroy()
        self.materias_grupo_vars.clear()

        if not sem_str or not sem_str.isdigit():
            ttk.Label(
                self.frame_mat_grp_checks,
                text="Ingresa un semestre para seleccionar materias",
                style='fondo.TLabel',
                foreground='#7E8B9B',
                font=self._fuente_sub
            ).pack(padx=10, pady=10)
            return

        sid = int(sem_str)
        conn = get_conexion()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT materia_id, nombre, tipo FROM materias WHERE semestre_id = %s ORDER BY materia_id", (sid,))
        materias_sem = cur.fetchall()
        cur.close()
        conn.close()

        if not materias_sem:
            ttk.Label(
                self.frame_mat_grp_checks,
                text=f"No hay materias registradas para el semestre {sid}",
                style='fondo.TLabel',
                foreground='#FFB020',
                font=self._fuente_sub
            ).pack(padx=10, pady=10)
            return

        for m_id, m_nom, m_tipo in materias_sem:
            marcado = (m_id in materias_preseleccionadas) if materias_preseleccionadas is not None else False
            var = tk.BooleanVar(value=marcado)
            self.materias_grupo_vars[m_id] = (var, m_nom)
            tipo_ui = self._ui_tipo_materia_salon(m_tipo)
            cb = ttk.Checkbutton(
                self.frame_mat_grp_checks,
                text=f"{m_id} - {m_nom} ({tipo_ui})",
                variable=var,
                style='Custom.TCheckbutton'
            )
            cb.pack(fill='x', padx=8, pady=3, anchor='w')

    def cargar_grupo_seleccionado(self, event):
        item = self.tabla_grupos.focus()
        if not item:
            return
        v = self.tabla_grupos.item(item, "values")
        grupo_id = str(v[0]).strip().upper()
        nivel = str(v[1]).strip()
        cupo = str(v[2]).strip() if len(v) > 2 else "30"
        self.entry_grupo_id.delete(0, tk.END)
        self.entry_grupo_nivel.delete(0, tk.END)
        self.entry_grupo_cupo.delete(0, tk.END)
        self.entry_grupo_cupo.insert(0, "30")
        self.entry_grupo_cupo.delete(0, tk.END)
        self.entry_grupo_id.insert(0, grupo_id)
        self.entry_grupo_nivel.insert(0, nivel)
        self.entry_grupo_cupo.insert(0, cupo)

        materias_vinculadas = set()
        conn = get_conexion()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT materia_id FROM grupo_materias WHERE grupo_id = %s", (grupo_id,))
                materias_vinculadas = {row[0] for row in cur.fetchall()}
            except Exception:
                materias_vinculadas = set()
            finally:
                cur.close()
                conn.close()

        self._on_cambio_semestre_grupo(materias_preseleccionadas=materias_vinculadas)

    def evento_grupos(self):
        self.master.update_idletasks()
        g = self.entry_grupo_id.get().strip().upper()
        n = self.entry_grupo_nivel.get().strip()
        cupo_val = self.entry_grupo_cupo.get().strip() or "30" 
        if not g or len(g) > 20:
            messagebox.showwarning("Aviso", "El identificador del grupo es obligatorio y debe tener hasta 20 caracteres.")
            return
        if not n.isascii() or not n.isdigit() or len(n) > 2:
            messagebox.showwarning("Aviso", "El semestre debe ser un número entero de hasta 2 dígitos.")
            return

        seleccionadas = [(m_id, nom) for m_id, (var, nom) in self.materias_grupo_vars.items() if var.get()]
        if not seleccionadas:
            messagebox.showwarning("Aviso", "Debes seleccionar al menos una materia para vincular al grupo.")
            return

        lista_txt = "\n".join(f"- {nom} ({m_id})" for m_id, nom in seleccionadas)
        mensaje = (
            f"El grupo {g} tiene estas materias seleccionadas:\n\n"
            f"{lista_txt}\n\n"
            "¿Desea guardar esta configuración?"
        )
        if not messagebox.askyesno("Confirmar Configuración", mensaje):
            # No - modificar configuración
            return

        registro = grupo(g, n, materias=[m[0] for m in seleccionadas], cupo=cupo_val)
        if registro.exito:
            # Preasignar aula y horarios automáticamente para que esté disponible de inmediato en todas las vistas
            try:
                from src.motor_preasignacion import GeneradorPreasignacion
                motor = GeneradorPreasignacion()
                res_pre = motor.preasignar_grupo(g)
                if res_pre.get('exito'):
                    print(f"[PREASIGNACION AUTO] {res_pre.get('mensaje')}")
            except Exception as e:
                print(f"[PREASIGNACION AUTO ERROR] {e}")

            self.limpiar_campos_grupo()
            self._refresh_all()

    def limpiar_campos_grupo(self):
        self.entry_grupo_id.delete(0, tk.END)
        self.entry_grupo_nivel.delete(0, tk.END)
        self.entry_grupo_cupo.delete(0, tk.END)
        self.entry_grupo_cupo.insert(0, "30")
        self.materias_grupo_vars.clear()
        for w in self.frame_mat_grp_checks.winfo_children():
            w.destroy()
        ttk.Label(
            self.frame_mat_grp_checks,
            text="Ingresa un semestre para seleccionar materias",
            style='fondo.TLabel',
            foreground='#7E8B9B',
            font=self._fuente_sub
        ).pack(padx=10, pady=10)

    def eliminar_grupo(self):
        grupo_id = self.entry_grupo_id.get().strip().upper()
        if not grupo_id:
            return
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar el grupo '{grupo_id}'?"):
            from src.conexion import obtener_cursor
            exito = False
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM horarios WHERE asignacion_id IN (SELECT asignacion_id FROM asignaciones WHERE grupo_id = %s)", (grupo_id,))
                    cur.execute("DELETE FROM asignaciones WHERE grupo_id = %s", (grupo_id,))
                    cur.execute("DELETE FROM grupo_materias WHERE grupo_id = %s", (grupo_id,))
                    cur.execute("DELETE FROM grupos WHERE grupo_id = %s", (grupo_id,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self.limpiar_campos_grupo()
                self._refresh_all()
                messagebox.showinfo("Éxito", "Grupo eliminado correctamente.")

    def mostrar_datos_grupos(self):
        self.cache_grupos = []
        conn = get_conexion()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT grupo_id, nivel, COALESCE(cupo, 30) FROM grupos ORDER BY nivel, grupo_id")
                self.cache_grupos = cur.fetchall()
            except Exception:
                self.cache_grupos = []
            finally:
                cur.close()
                conn.close()
        self.refrescar_tabla_grp(self.cache_grupos)

    def refrescar_tabla_grp(self, datos):
        if hasattr(self, 'tabla_grupos'):
            self.tabla_grupos.delete(*self.tabla_grupos.get_children())
            for d in datos:
                self.tabla_grupos.insert("", "end", values=d)

    def filtrar_grupos(self):
        t = self.sv_busqueda_grupo.get().lower()
        s = self.sv_filtro_semestre_grupo.get()
        if not hasattr(self, 'cache_grupos'):
            self.mostrar_datos_grupos()
            return
        f = [g for g in self.cache_grupos if (t in str(g[0]).lower() or t in str(g[1]).lower() or (len(g) > 2 and t in str(g[2]).lower())) and (s == "Todos" or str(g[1]) == s)]
        self.refrescar_tabla_grp(f)

    def _mostrar_dialogo_modo_preasignacion(self):
        """
        Muestra un diálogo de confirmación para elegir si se preasignan
        todos los grupos o solo los grupos que aún no tienen aula asignada.
        Retorna 'sin_aula', 'todos', o None (cancelar).
        """
        seleccion = [None]

        dialogo = tk.Toplevel(self.master)
        dialogo.title("Preasignación de Aulas y Horarios")
        dialogo.transient(self.master)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')
        dialogo.geometry("540x360")
        dialogo.resizable(False, False)

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=20, pady=16)

        ttk.Label(
            f_cont,
            text="Preasignación de Aulas y Horarios",
            background='#0A0F1E',
            foreground='#38BDF8',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 6))

        ttk.Label(
            f_cont,
            text="¿Qué grupos desea preasignar?",
            background='#0A0F1E',
            foreground='#FFFFFF',
            font=self._fuente_sub
        ).pack(anchor='w', pady=(0, 10))

        # Opción 1: Solo grupos sin aula (Recomendado)
        f_op1 = ttk.LabelFrame(f_cont, text="Opción Recomendada", style='blue.TFrame')
        f_op1.pack(fill='x', pady=6)

        def _sel_sin_aula():
            seleccion[0] = "sin_aula"
            dialogo.destroy()

        ttk.Button(
            f_op1,
            text=" Solo grupos que no tienen aula aún",
            image=IconManager.get("bolt", 16),
            compound="left",
            command=_sel_sin_aula
        ).pack(anchor='w', padx=10, pady=(6, 2))

        ttk.Label(
            f_op1,
            text="• Conserva intactos los grupos y materias ya asignadas a profesores.\n• Solo asigna salón y horarios a los grupos pendientes.",
            background='#0A0F1E',
            foreground='#81C784',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', padx=10, pady=(0, 6))

        # Opción 2: Todos los grupos
        f_op2 = ttk.LabelFrame(f_cont, text="Reasignación Total", style='blue.TFrame')
        f_op2.pack(fill='x', pady=6)

        def _sel_todos():
            if messagebox.askyesno(
                "Confirmar Reasignación Total",
                "¿Estás seguro de querer preasignar TODOS los grupos registrados?\n\n"
                "Se reorganizarán los salones y horarios para toda la institución.\n\n"
                "¿Deseas continuar?"
            ):
                seleccion[0] = "todos"
                dialogo.destroy()

        ttk.Button(
            f_op2,
            text=" Todos los grupos registrados",
            image=IconManager.get("refresh", 16),
            compound="left",
            command=_sel_todos
        ).pack(anchor='w', padx=10, pady=(6, 2))

        ttk.Label(
            f_op2,
            text="• Vuelve a distribuir las aulas y horarios de todos los grupos desde cero.\n• Mantendrá las vinculaciones docentes siempre que sea compatible.",
            background='#0A0F1E',
            foreground='#FFB74D',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', padx=10, pady=(0, 6))

        # Botón cancelar
        f_btn = ttk.Frame(f_cont, style='blue.TFrame')
        f_btn.pack(fill='x', side='bottom', pady=(10, 0))

        def _cancelar():
            seleccion[0] = None
            dialogo.destroy()

        ttk.Button(f_btn, text="Cancelar", command=_cancelar).pack(side='right', padx=4)

        dialogo.wait_window()
        return seleccion[0]

    def iniciar_preasignacion(self):
        """
        Ejecuta la preasignación automática de aulas y horarios según la selección del usuario.
        """
        modo = self._mostrar_dialogo_modo_preasignacion()
        if not modo:
            return

        solo_sin_aula = (modo == "sin_aula")

        # Auto-respaldo previo por seguridad
        try:
            from src.gestor_restauracion import GestorRestauracion
            GestorRestauracion.crear_punto(
                nombre=f"Auto-respaldo desde Personal ({'solo sin aula' if solo_sin_aula else 'total'})",
                descripcion="Generado automáticamente antes de iniciar preasignación de aulas"
            )
        except Exception as e:
            print(f"Error creando auto-respaldo previo: {e}")

        from src.motor_preasignacion import GeneradorPreasignacion
        generador = GeneradorPreasignacion()
        resultado = generador.ejecutar(solo_sin_aula=solo_sin_aula)

        if not resultado.get("exito"):
            messagebox.showerror("Error en Preasignación", resultado.get("mensaje", "Ocurrió un error desconocido."))
            return

        self._refresh_all()

        total_grupos = resultado.get("total_grupos", 0)
        total_materias = resultado.get("materias_asignadas", 0)
        total_horarios = resultado.get("horarios_generados", 0)
        salones = resultado.get("salones_utilizados", [])
        alertas = resultado.get("alertas", [])
        resumen_grupos = resultado.get("resumen_grupos", [])

        detalles = "\n".join(resumen_grupos[:10])
        if len(resumen_grupos) > 10:
            detalles += f"\n... y {len(resumen_grupos) - 10} grupos más."

        msg = (
            f"Preasignación completada exitosamente.\n\n"
            f"• Grupos procesados: {total_grupos}\n"
            f"• Materias preasignadas: {total_materias}\n"
            f"• Bloques de horario: {total_horarios}\n"
            f"• Aulas utilizadas: {', '.join(salones) if salones else 'Ninguna'}\n\n"
            f"Distribución:\n{detalles}"
        )
        if alertas:
            msg += f"\n\nObservaciones ({len(alertas)}):\n" + "\n".join(f"- {a}" for a in alertas[:5])

        messagebox.showinfo("Preasignación Exitosa", msg)
