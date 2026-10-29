# -*- coding: utf-8 -*-
"""
Diálogo Interactivo para Configuración y Envío de Cédulas Horarias por Correo en SAGA.
"""

import os
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from src.gestor_correo import GestorCorreo
from src.generador_sabana import GeneradorSabana
from src.UI.icon_manager import IconManager


class DialogoEnvioCorreo(tk.Toplevel):
    def __init__(self, parent, profesor_id_seleccionado=None):
        super().__init__(parent)
        self.profesor_id_sel = profesor_id_seleccionado

        self.title("Envío de Cédulas por Correo Electrónico — SAGA")
        self.geometry("740x620")
        self.minsize(680, 560)
        self.configure(bg="#0A0F1E")
        self.transient(parent)
        self.grab_set()

        self.config_correo = GestorCorreo.cargar_configuracion()
        self.lista_profesores_carga = GestorCorreo.obtener_profesores_con_carga()

        self._construir_ui()
        self._centrar_en_padre(parent)

    def _centrar_en_padre(self, parent):
        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _construir_ui(self):
        # Encabezado
        f_top = tk.Frame(self, bg="#111827", padx=16, pady=12, highlightthickness=1, highlightbackground="#1F2937")
        f_top.pack(fill="x", padx=14, pady=(12, 6))

        tk.Label(
            f_top,
            text="📧 Envío Institucional de Cédulas Horarias por Correo",
            font=("Segoe UI", 12, "bold"),
            fg="#F3F4F6",
            bg="#111827"
        ).pack(anchor="w")

        tk.Label(
            f_top,
            text="Genera automáticamente los PDFs oficiales con escudos de la UAEMéx y los envía al correo de cada docente.",
            font=("Segoe UI", 9),
            fg="#9CA3AF",
            bg="#111827"
        ).pack(anchor="w", pady=(3, 0))

        # Notebook con pestañas
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=6)

        self.tab_envio = ttk.Frame(self.notebook, style='blue.TFrame')
        self.tab_config = ttk.Frame(self.notebook, style='blue.TFrame')

        self.notebook.add(self.tab_envio, text="📤 Enviar Cédulas")
        self.notebook.add(self.tab_config, text="⚙️ Configuración Servidor SMTP")

        self._construir_tab_envio()
        self._construir_tab_config()

        # Botón inferior para cerrar
        f_foot = tk.Frame(self, bg="#0A0F1E", padx=14, pady=8)
        f_foot.pack(fill="x")
        ttk.Button(f_foot, text="Cerrar", command=self.destroy).pack(side="right")

    # =========================================================================
    # PESTAÑA 1: ENVÍO DE CÉDULAS
    # =========================================================================
    def _construir_tab_envio(self):
        f = self.tab_envio

        # 1. Destinatarios
        f_dest = ttk.LabelFrame(f, text="Destinatarios", style='blue.TFrame')
        f_dest.pack(fill="x", padx=12, pady=(10, 6))

        self.var_modo_envio = tk.StringVar(value="todos")

        # Buscar info del profesor seleccionado
        prof_sel_info = None
        if self.profesor_id_sel:
            for p in self.lista_profesores_carga:
                if p["profesor_id"] == self.profesor_id_sel:
                    prof_sel_info = p
                    break

        if prof_sel_info:
            correo_p = prof_sel_info.get("correo_institucional") or "Sin correo registrado"
            txt_indiv = f"Únicamente al docente seleccionado: {prof_sel_info['nombre']} ({correo_p})"
            rb_indiv = ttk.Radiobutton(f_dest, text=txt_indiv, variable=self.var_modo_envio, value="individual", style='Custom.TRadiobutton')
            rb_indiv.pack(anchor="w", padx=10, pady=4)
            self.var_modo_envio.set("individual")
        else:
            rb_indiv = ttk.Radiobutton(f_dest, text="Docente seleccionado (No hay profesor seleccionado en la tabla)", variable=self.var_modo_envio, value="individual", state="disabled", style='Custom.TRadiobutton')
            rb_indiv.pack(anchor="w", padx=10, pady=4)

        con_correo = sum(1 for p in self.lista_profesores_carga if p.get("correo_institucional") and "@" in p["correo_institucional"])
        txt_todos = f"Todos los profesores con carga horaria ({len(self.lista_profesores_carga)} docentes, {con_correo} con correo válido)"
        rb_todos = ttk.Radiobutton(f_dest, text=txt_todos, variable=self.var_modo_envio, value="todos", style='Custom.TRadiobutton')
        rb_todos.pack(anchor="w", padx=10, pady=(2, 6))

        # 2. Plantilla de Correo
        f_plantilla = ttk.LabelFrame(f, text="Mensaje y Plantilla Institucional", style='blue.TFrame')
        f_plantilla.pack(fill="both", expand=True, padx=12, pady=6)

        f_asunto = ttk.Frame(f_plantilla, style='blue.TFrame')
        f_asunto.pack(fill="x", padx=10, pady=(6, 4))
        ttk.Label(f_asunto, text="Asunto:", background="#0A0F1E", foreground="white", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.entry_asunto = ttk.Entry(f_asunto, font=("Segoe UI", 9))
        self.entry_asunto.pack(side="left", fill="x", expand=True)
        self.entry_asunto.insert(0, self.config_correo.get("asunto_plantilla", "UAEMéx Tianguistenco — Cédula Oficial de Carga Horaria"))

        ttk.Label(
            f_plantilla,
            text="Cuerpo del correo (la etiqueta {nombre} se reemplaza automáticamente con el nombre de cada docente):",
            background="#0A0F1E",
            foreground="#9CA3AF",
            font=("Segoe UI", 8)
        ).pack(anchor="w", padx=10, pady=(6, 2))

        self.txt_cuerpo = tk.Text(f_plantilla, height=7, font=("Consolas", 9), bg="#111827", fg="#F3F4F6", relief="flat", bd=2)
        self.txt_cuerpo.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.txt_cuerpo.insert("1.0", self.config_correo.get("cuerpo_plantilla", ""))

        # 3. Barra de progreso y botón de inicio
        f_accion = ttk.Frame(f, style='blue.TFrame')
        f_accion.pack(fill="x", padx=12, pady=(6, 10))

        self.lbl_estado_envio = ttk.Label(f_accion, text="Listo para iniciar el envío.", background="#0A0F1E", foreground="#FBBF24", font=("Segoe UI", 9))
        self.lbl_estado_envio.pack(side="left")

        self.btn_enviar = ttk.Button(
            f_accion,
            text="📤 Iniciar Envío de Cédulas",
            image=IconManager.get("mail", 16),
            compound="left",
            command=self._iniciar_proceso_envio
        )
        self.btn_enviar.pack(side="right")

        self.progress_bar = ttk.Progressbar(f, mode="determinate")
        self.progress_bar.pack(fill="x", padx=12, pady=(0, 4))

    # =========================================================================
    # PESTAÑA 2: CONFIGURACIÓN SMTP
    # =========================================================================
    def _construir_tab_config(self):
        f = self.tab_config

        f_form = ttk.LabelFrame(f, text="Parámetros del Servidor de Correo (SMTP)", style='blue.TFrame')
        f_form.pack(fill="both", expand=True, padx=12, pady=10)

        # Preset
        f_pre = ttk.Frame(f_form, style='blue.TFrame')
        f_pre.pack(fill="x", padx=12, pady=6)
        ttk.Label(f_pre, text="Servicio preconfigurado:", background="#0A0F1E", foreground="white", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))
        self.combo_preset = ttk.Combobox(f_pre, values=list(GestorCorreo.PRESETS.keys()), state="readonly", width=25)
        self.combo_preset.set(self.config_correo.get("preset", "Office 365 (UAEMéx)"))
        self.combo_preset.pack(side="left")
        self.combo_preset.bind("<<ComboboxSelected>>", self._on_preset_cambio)

        # Servidor y Puerto
        f_sp = ttk.Frame(f_form, style='blue.TFrame')
        f_sp.pack(fill="x", padx=12, pady=6)
        ttk.Label(f_sp, text="Servidor SMTP:", background="#0A0F1E", foreground="white", font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        self.entry_servidor = ttk.Entry(f_sp, width=28)
        self.entry_servidor.pack(side="left", padx=(0, 16))
        self.entry_servidor.insert(0, self.config_correo.get("servidor", "smtp.office365.com"))

        ttk.Label(f_sp, text="Puerto:", background="#0A0F1E", foreground="white", font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        self.entry_puerto = ttk.Entry(f_sp, width=8)
        self.entry_puerto.pack(side="left", padx=(0, 16))
        self.entry_puerto.insert(0, str(self.config_correo.get("puerto", 587)))

        self.var_tls = tk.BooleanVar(value=self.config_correo.get("usar_tls", True))
        ttk.Checkbutton(f_sp, text="Usar STARTTLS", variable=self.var_tls, style='Custom.TCheckbutton').pack(side="left")

        # Correo y Contraseña
        f_cred = ttk.Frame(f_form, style='blue.TFrame')
        f_cred.pack(fill="x", padx=12, pady=6)

        ttk.Label(f_cred, text="Correo Remitente:", background="#0A0F1E", foreground="white", font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        self.entry_remitente = ttk.Entry(f_cred, width=32)
        self.entry_remitente.pack(side="left", padx=(0, 16))
        self.entry_remitente.insert(0, self.config_correo.get("remitente", ""))

        ttk.Label(f_cred, text="Contraseña / App Token:", background="#0A0F1E", foreground="white", font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        self.entry_pwd = ttk.Entry(f_cred, width=20, show="*")
        self.entry_pwd.pack(side="left", padx=(0, 4))
        self.entry_pwd.insert(0, self.config_correo.get("password", ""))

        self.var_ver_pwd = tk.BooleanVar(value=False)
        def _toggle_pwd():
            self.entry_pwd.config(show="" if self.var_ver_pwd.get() else "*")
        ttk.Checkbutton(f_cred, text="👁", variable=self.var_ver_pwd, command=_toggle_pwd, style='Custom.TCheckbutton').pack(side="left")

        # Mensaje de ayuda
        tk.Label(
            f_form,
            text="💡 Nota: Para cuentas de Office 365 o Gmail con verificación en dos pasos (2FA), se recomienda generar una 'Contraseña de Aplicación'.",
            bg="#0A0F1E",
            fg="#9CA3AF",
            font=("Segoe UI", 8),
            justify="left"
        ).pack(anchor="w", padx=12, pady=(12, 6))

        # Botones de test y guardar
        f_btns_cfg = ttk.Frame(f_form, style='blue.TFrame')
        f_btns_cfg.pack(fill="x", padx=12, pady=12)

        ttk.Button(
            f_btns_cfg,
            text="🔍 Probar Conexión SMTP",
            image=IconManager.get("refresh", 16),
            compound="left",
            command=self._probar_conexion
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            f_btns_cfg,
            text="💾 Guardar Configuración",
            image=IconManager.get("save", 16),
            compound="left",
            command=self._guardar_configuracion
        ).pack(side="left")

    def _on_preset_cambio(self, event=None):
        preset_nombre = self.combo_preset.get()
        p = GestorCorreo.PRESETS.get(preset_nombre)
        if p and p["servidor"]:
            self.entry_servidor.delete(0, tk.END)
            self.entry_servidor.insert(0, p["servidor"])
            self.entry_puerto.delete(0, tk.END)
            self.entry_puerto.insert(0, str(p["puerto"]))
            self.var_tls.set(p["usar_tls"])

    def _obtener_config_desde_ui(self):
        try:
            puerto = int(self.entry_puerto.get().strip() or 587)
        except ValueError:
            puerto = 587

        return {
            "preset": self.combo_preset.get(),
            "servidor": self.entry_servidor.get().strip(),
            "puerto": puerto,
            "usar_tls": self.var_tls.get(),
            "remitente": self.entry_remitente.get().strip(),
            "password": self.entry_pwd.get().strip(),
            "asunto_plantilla": self.entry_asunto.get().strip(),
            "cuerpo_plantilla": self.txt_cuerpo.get("1.0", tk.END).strip()
        }

    def _probar_conexion(self):
        cfg = self._obtener_config_desde_ui()
        exito, msg = GestorCorreo.probar_conexion(cfg)
        if exito:
            messagebox.showinfo("Conexión Exitosa", msg, parent=self)
        else:
            messagebox.showerror("Fallo de Conexión", msg, parent=self)

    def _guardar_configuracion(self):
        cfg = self._obtener_config_desde_ui()
        exito, msg = GestorCorreo.guardar_configuracion(cfg)
        self.config_correo = cfg
        if exito:
            messagebox.showinfo("Configuración Guardada", msg, parent=self)
        else:
            messagebox.showerror("Error", msg, parent=self)

    # =========================================================================
    # LÓGICA DE ENVÍO ASÍNCRONO
    # =========================================================================
    def _iniciar_proceso_envio(self):
        cfg = self._obtener_config_desde_ui()
        if not cfg["remitente"] or not cfg["password"] or not cfg["servidor"]:
            messagebox.showwarning(
                "Configuración Incompleta",
                "Debes configurar el servidor SMTP, correo remitente y contraseña en la pestaña 'Configuración Servidor SMTP'.",
                parent=self
            )
            self.notebook.select(self.tab_config)
            return

        modo = self.var_modo_envio.get()
        if modo == "individual":
            destinatarios = [p for p in self.lista_profesores_carga if p["profesor_id"] == self.profesor_id_sel]
            if not destinatarios:
                messagebox.showwarning("Aviso", "No se encontró el profesor seleccionado.", parent=self)
                return
        else:
            destinatarios = [p for p in self.lista_profesores_carga if p.get("correo_institucional") and "@" in p["correo_institucional"]]
            if not destinatarios:
                messagebox.showwarning(
                    "Sin Correos",
                    "No se encontraron profesores con carga horaria que tengan correo institucional registrado.\n"
                    "Puedes capturar los correos en la pestaña Personal -> Profesores.",
                    parent=self
                )
                return

        total = len(destinatarios)
        msg_confirmar = (
            f"¿Desea iniciar el envío de cédulas horarias a {total} docente(s)?\n\n"
            f"• Remitente: {cfg['remitente']}\n"
            f"• Servidor: {cfg['servidor']}:{cfg['puerto']}\n"
            f"• Se generará y adjuntará la cédula individual oficial en PDF."
        )

        if not messagebox.askyesno("Confirmar Envío", msg_confirmar, parent=self):
            return

        self.btn_enviar.config(state="disabled")
        self.progress_bar["maximum"] = total
        self.progress_bar["value"] = 0

        # Ejecutar en segundo plano para no congelar la UI
        hilo = threading.Thread(target=self._tarea_envio, args=(cfg, destinatarios), daemon=True)
        hilo.start()

    def _tarea_envio(self, cfg, destinatarios):
        total = len(destinatarios)
        enviados = 0
        fallidos = []

        temp_dir = tempfile.mkdtemp(prefix="saga_cedulas_")

        for idx, prof in enumerate(destinatarios, start=1):
            nombre = prof.get("nombre", "Docente")
            pid = prof.get("profesor_id")
            correo = prof.get("correo_institucional")

            # Actualizar progreso en UI
            self.after(0, lambda i=idx, n=nombre: self.lbl_estado_envio.config(
                text=f"Enviando ({i}/{total}): {n}...",
                foreground="#38BDF8"
            ))
            self.after(0, lambda i=idx: self.progress_bar.configure(value=i))

            # 1. Generar PDF individual de la cédula del profesor
            ruta_pdf = os.path.join(temp_dir, f"Cedula_{pid}.pdf")
            try:
                res_pdf = GeneradorSabana.generar_pdf_fichas_profesores(
                    ruta_archivo=ruta_pdf,
                    filtro_profesor_id=pid
                )
                if not res_pdf.get("exito"):
                    fallidos.append((nombre, correo, f"Error generando PDF: {res_pdf.get('mensaje')}"))
                    continue
            except Exception as e:
                fallidos.append((nombre, correo, f"Error generando PDF: {e}"))
                continue

            # 2. Enviar correo vía SMTP
            exito_envio, msg_envio = GestorCorreo.enviar_cedula_profesor(cfg, prof, ruta_pdf)
            if exito_envio:
                enviados += 1
            else:
                fallidos.append((nombre, correo, msg_envio))

            # Limpiar archivo temporal
            try:
                if os.path.exists(ruta_pdf):
                    os.remove(ruta_pdf)
            except Exception:
                pass

        # Limpiar carpeta temporal
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass

        # Mostrar resultados en UI principal
        self.after(0, lambda: self._finalizar_envio(enviados, fallidos, total))

    def _finalizar_envio(self, enviados, fallidos, total):
        self.btn_enviar.config(state="normal")
        self.lbl_estado_envio.config(
            text=f"Proceso finalizado: {enviados} de {total} enviados exitosamente.",
            foreground="#34D399" if not fallidos else "#FBBF24"
        )

        res_msg = f"Resumen de Envío:\n\n• Cédulas enviadas exitosamente: {enviados}\n• Fallidos: {len(fallidos)}\n"
        if fallidos:
            res_msg += "\nDetalles de envíos no realizados:\n"
            for nom, mail, mot in fallidos[:8]:
                res_msg += f"- {nom} ({mail}): {mot}\n"
            if len(fallidos) > 8:
                res_msg += f"... y {len(fallidos) - 8} más.\n"

        if not fallidos:
            messagebox.showinfo("Envío Exitoso", res_msg, parent=self)
        else:
            messagebox.showwarning("Envío Concluido con Alertas", res_msg, parent=self)
