# -*- coding: utf-8 -*-
"""
Módulo Gestor de Envíos de Correo para SAGA UAEMéx.
Permite configurar el servidor SMTP (Office 365, Gmail, etc.) y enviar
cédulas de carga horaria en formato PDF a los profesores de manera individual o masiva.
"""

import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from src.conexion import get_ruta_base_datos, obtener_cursor_dict


class GestorCorreo:
    PRESETS = {
        "Office 365 (UAEMéx)": {
            "servidor": "smtp.office365.com",
            "puerto": 587,
            "usar_tls": True
        },
        "Gmail / Google Workspace": {
            "servidor": "smtp.gmail.com",
            "puerto": 587,
            "usar_tls": True
        },
        "Outlook / Hotmail": {
            "servidor": "smtp-mail.outlook.com",
            "puerto": 587,
            "usar_tls": True
        },
        "Personalizado": {
            "servidor": "",
            "puerto": 587,
            "usar_tls": True
        }
    }

    @classmethod
    def _ruta_config(cls):
        dir_saga = os.path.dirname(get_ruta_base_datos())
        return os.path.join(dir_saga, "config_correo.json")

    @classmethod
    def cargar_configuracion(cls):
        ruta = cls._ruta_config()
        if os.path.exists(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    return cfg
            except Exception as e:
                print(f"Error leyendo configuración de correo: {e}")

        # Configuración predeterminada institucional
        return {
            "preset": "Office 365 (UAEMéx)",
            "servidor": "smtp.office365.com",
            "puerto": 587,
            "usar_tls": True,
            "remitente": "",
            "password": "",
            "asunto_plantilla": "UAEMéx Tianguistenco — Cédula Oficial de Carga Horaria",
            "cuerpo_plantilla": (
                "Estimado(a) {nombre}:\n\n"
                "Por medio de la presente, la Coordinación de Carrera del Centro Universitario "
                "UAEM Tianguistenco le hace entrega de su Cédula Oficial de Carga Horaria "
                "correspondiente al presente ciclo académico.\n\n"
                "En el archivo PDF adjunto encontrará el desglose detallado de sus asignaturas, "
                "grupos, aulas y horarios asignados.\n\n"
                "Favor de revisar la información y acudir a la coordinación para la firma correspondiente.\n\n"
                "Atentamente,\n"
                "Coordinación de Carrera\n"
                "Centro Universitario UAEM Tianguistenco"
            )
        }

    @classmethod
    def guardar_configuracion(cls, cfg):
        ruta = cls._ruta_config()
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
            return True, "Configuración guardada correctamente."
        except Exception as e:
            return False, f"Error al guardar la configuración: {e}"

    @classmethod
    def probar_conexion(cls, cfg):
        servidor = cfg.get("servidor", "").strip()
        puerto = int(cfg.get("puerto", 587))
        usar_tls = cfg.get("usar_tls", True)
        remitente = cfg.get("remitente", "").strip()
        password = cfg.get("password", "").strip()

        if not servidor or not remitente or not password:
            return False, "Debes completar el servidor, correo remitente y contraseña."

        try:
            server = smtplib.SMTP(servidor, puerto, timeout=15)
            server.ehlo()
            if usar_tls:
                server.starttls()
                server.ehlo()
            server.login(remitente, password)
            server.quit()
            return True, "¡Conexión y autenticación exitosa con el servidor SMTP!"
        except Exception as e:
            return False, f"Fallo al conectar o autenticar con {servidor}:{puerto}\nDetalle: {e}"

    @classmethod
    def obtener_profesores_con_carga(cls):
        """
        Retorna la lista de docentes que tienen materias asignadas y correo electrónico registrado.
        """
        profesores = []
        with obtener_cursor_dict() as ctx:
            if not ctx:
                return []
            cur, _ = ctx
            cur.execute("""
                SELECT DISTINCT p.profesor_id, p.nombre, p.correo_institucional, p.no_cuenta,
                       COUNT(DISTINCT a.asignacion_id) as total_materias,
                       ROUND(SUM(m.horas_semana), 1) as total_horas
                FROM profesores p
                JOIN asignaciones a ON p.profesor_id = a.profesor_id
                JOIN materias m ON a.materia_id = m.materia_id
                WHERE p.profesor_id != 'SIN_ASIGNAR'
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
                GROUP BY p.profesor_id, p.nombre, p.correo_institucional, p.no_cuenta
                ORDER BY p.nombre
            """)
            profesores = cur.fetchall()
        return profesores

    @classmethod
    def enviar_cedula_profesor(cls, cfg, prof_info, ruta_pdf):
        """
        Envía un correo electrónico con el PDF adjunto al docente especificado.
        """
        destinatario = (prof_info.get("correo_institucional") or "").strip()
        nombre_prof = prof_info.get("nombre", "Docente")

        if not destinatario or "@" not in destinatario:
            return False, f"El profesor '{nombre_prof}' no tiene un correo institucional válido."

        if not os.path.exists(ruta_pdf):
            return False, f"No se encontró el archivo PDF generado: {ruta_pdf}"

        remitente = cfg.get("remitente", "").strip()
        asunto_raw = cfg.get("asunto_plantilla", "Cédula de Carga Horaria")
        cuerpo_raw = cfg.get("cuerpo_plantilla", "")

        asunto = asunto_raw.replace("{nombre}", nombre_prof)
        cuerpo = cuerpo_raw.replace("{nombre}", nombre_prof)

        # Construir mensaje MIME
        msg = MIMEMultipart()
        msg["From"] = f"Coordinación UAEM Tianguistenco <{remitente}>"
        msg["To"] = destinatario
        msg["Subject"] = asunto

        # Cuerpo del mensaje
        msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

        # Adjuntar PDF
        nombre_archivo_adjunto = f"Cedula_Carga_Horaria_{nombre_prof.replace(' ', '_')}.pdf"
        try:
            with open(ruta_pdf, "rb") as f:
                adjunto = MIMEApplication(f.read(), _subtype="pdf")
                adjunto.add_header("Content-Disposition", "attachment", filename=nombre_archivo_adjunto)
                msg.attach(adjunto)
        except Exception as e:
            return False, f"Error adjuntando el archivo PDF: {e}"

        # Enviar vía SMTP
        servidor = cfg.get("servidor", "").strip()
        puerto = int(cfg.get("puerto", 587))
        usar_tls = cfg.get("usar_tls", True)
        password = cfg.get("password", "").strip()

        try:
            server = smtplib.SMTP(servidor, puerto, timeout=20)
            server.ehlo()
            if usar_tls:
                server.starttls()
                server.ehlo()
            server.login(remitente, password)
            server.send_message(msg)
            server.quit()
            return True, f"Correo enviado exitosamente a {destinatario}"
        except Exception as e:
            return False, f"Error al enviar correo a {destinatario}: {e}"
