# Módulo de Envío de Cédulas Horarias por Correo Electrónico (Sin Implementar)

> **Estado:** Resguardado / Desacoplado de la interfaz de usuario de SAGA  
> **Fecha de archivo:** Octubre 2026  
> **Propósito:** Conservar la lógica funcional de envío de correos electrónicos y PDFs para futuros equipos de desarrollo.

---

## 📌 Contexto y Motivo del Desacople

Se diseñó e implementó un módulo completo para enviar las cédulas horarias oficiales en formato PDF a los profesores vía correo electrónico institucional. 

Sin embargo, tras la evaluación de experiencia de usuario, se determinó que **la configuración manual de parámetros de red y servidores SMTP (servidor, puerto, TLS, usuario y contraseñas de aplicación)** resulta poco cómoda y técnica para los coordinadores académicos de carrera, quienes requieren flujos de trabajo más intuitivos o integraciones nativas sin configuración manual.

Por este motivo, se desacopló el módulo de la interfaz principal de SAGA, manteniendo el código fuente intacto en este directorio para que futuras iteraciones o equipos de desarrollo puedan reactivarlo o modernizarlo.

---

## 📂 Archivos del Módulo

1. **`gestor_correo.py`**:
   - Backend con la clase `GestorCorreo`.
   - Manejo de presets para Office 365 (`smtp.office365.com`), Gmail y Outlook.
   - `probar_conexion(cfg)`: Valida credenciales SMTP en tiempo real.
   - `enviar_cedula_profesor(cfg, prof_info, ruta_pdf)`: Construye mensajes `MIMEMultipart` con adjuntos PDF codificados en base64.
   - `obtener_profesores_con_carga()`: Consulta en SQLite a los docentes con asignaciones y correo registrado.

2. **`dialogo_envio_correo.py`**:
   - Ventana modal interactiva en Tkinter (`DialogoEnvioCorreo`).
   - Pestaña 1: Configuración de destinatarios (individual o masivo), asunto y cuerpo con etiquetas dinámicas (`{nombre}`).
   - Pestaña 2: Configuración del servidor SMTP y pruebas de conexión.
   - Envío asíncrono con hilos (`threading.Thread`) y barra de progreso animada.

---

## 🚀 Recomendaciones para Futuros Equipos de Desarrollo

Si se desea reincorporar esta funcionalidad en versiones posteriores de SAGA, se recomienda considerar las siguientes mejoras arquitectónicas:

1. **Autenticación Institucional OAuth2 (Microsoft Graph API / Google Workspace API):**
   - En lugar de pedir contraseñas SMTP manuales (que frecuentemente se bloquean por directivas de seguridad 2FA/MFA institucional), integrar un botón de *"Iniciar sesión con cuenta @uaemex.mx"* usando OAuth2 / Microsoft Graph API.
2. **Servicio Webhook / Microservicio Backend:**
   - Centralizar el envío en una API o servidor escolar institucional para que la aplicación de escritorio solo envíe la orden de despacho sin manejar credenciales locales.
3. **Reactivación Rápida:**
   - Para reactivar el diálogo actual en caso necesario, solo se debe importar `DialogoEnvioCorreo` y vincularlo al evento del botón deseado en `src/UI/ventana_gestion.py`.
