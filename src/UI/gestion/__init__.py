# -*- coding: utf-8 -*-
"""
Submódulo de Gestión de Horarios y Asignaciones SAGA.
Ensambla la clase principal VentanaGestion mediante Mixins temáticos.
"""
import tkinter as tk
from tkinter import ttk, font
import unicodedata

from src.UI.gestion.gestion_base import GestionBaseMixin, ruta_recurso, _migrar_bd, _backfill_dias
from src.UI.gestion.gestion_layout import GestionLayoutMixin
from src.UI.gestion.gestion_asignaciones import GestionAsignacionesMixin
from src.UI.gestion.gestion_conflictos import GestionConflictosMixin
from src.UI.gestion.gestion_periodos_card import GestionPeriodosCardMixin
from src.UI.gestion.gestion_configuracion import GestionConfiguracionMixin
from src.UI.gestion.gestion_respaldos import GestionRespaldosMixin
from src.UI.gestion.gestion_motores_dialogos import GestionMotoresDialogosMixin
from src.UI.gestion.gestion_ver_horarios import GestionVerHorariosMixin

class VentanaGestion(
    GestionBaseMixin,
    GestionLayoutMixin,
    GestionAsignacionesMixin,
    GestionConflictosMixin,
    GestionPeriodosCardMixin,
    GestionConfiguracionMixin,
    GestionRespaldosMixin,
    GestionMotoresDialogosMixin,
    GestionVerHorariosMixin
):
    MAPA_DIAS = {"0": "Lunes", "1": "Martes", "2": "Miércoles", "3": "Jueves", "4": "Viernes", "5": "Sábado"}
    NOMBRES_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    _DIA_SIN_ACENTOS = {"lunes": "0", "martes": "1", "miercoles": "2", "jueves": "3", "viernes": "4", "sabado": "5", "domingo": "6"}

    def __init__(self, master_window=None, parent_frame=None):
        self.master_window = master_window
        self.parent_frame = parent_frame
        if parent_frame is not None:
            self.ventana = parent_frame
            self._is_embedded = True
        else:
            self.ventana = tk.Toplevel(master_window)
            self.ventana.title("Ventana de Gestión")
            self.ventana.state('zoomed')
            self.ventana.transient(master_window)
            self._is_embedded = False

        _migrar_bd()
        _backfill_dias()

        self._fuente_titulo = font.Font(family="Roboto", size=18, weight="bold")
        self._fuente_sub = font.Font(family="Roboto", size=12)
        self._fuente_label = font.Font(family="Roboto", size=10)
        self._fuente_btn = font.Font(family="Roboto", size=10, weight="bold")

        estilo = ttk.Style()
        estilo.configure('blue.TFrame', background='#0A0F1E')
        estilo.configure('TNotebook', background='#0A0F1E', borderwidth=0)
        estilo.configure('TNotebook.Tab', background='#1a1f3e', foreground='#ffffff', padding=[10, 2])
        estilo.map('TNotebook.Tab', background=[('selected', '#0A0F1E')], foreground=[('selected', '#6D583A')])
        estilo.configure('Custom.TCheckbutton', font=self._fuente_label, background='#0A0F1E', foreground='#ffffff')
        estilo.map('Custom.TCheckbutton',
            background=[('active', '#ffffff'), ('focus', '#ffffff'), ('pressed', '#ffffff')],
            foreground=[('active', '#000000'), ('focus', '#000000'), ('pressed', '#000000')]
        )

        self.profesores_map = {}
        self.materias_map = {}
        self.semestres_map = {}
        self.lista_maestra_semestres = []
        self.lista_maestra_materias = []
        self._lista_completa_profesores = []
        
        self.asignacion_seleccionada_id = None
        self.entidades_filtradas = []
        self._tensor_cargado = False
        self._ultimas_alertas = []
        self._last_width = 0
        self._last_height = 0
        self._scale_factor = 1.0
        self._en_operacion = False
        self._ultimo_config_path = None
        self._profesor_id_seleccionado = None
        self._debounce_after_id = None
        self._periodo_seleccionado = None
        self._semestres_filtrados = []
        self._wheel_delta = 0
        self._wheel_bindings = []
        self._after_busqueda_profesores_id = None
        self._after_busqueda_asignaciones_id = None
        self._disponibilidad_profesores = {}
        self._materia_grupo_seleccionada_id = None
        self._materias_grupo_cache = {}
        
        self.grupos_por_semestre = self._cargar_grupos_desde_bd()

        if not self._is_embedded:
            self.ventana.protocol("WM_DELETE_WINDOW", self._confirmar_cierre)
        self.construir_interfaz()
        self._post_init()
        if not self._is_embedded:
            self.ventana.wait_window()

__all__ = ['VentanaGestion', 'ruta_recurso', '_migrar_bd', '_backfill_dias']
