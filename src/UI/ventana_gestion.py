# -*- coding: utf-8 -*-
"""
Fachada del módulo de Gestión de Horarios y Asignaciones SAGA.
Reorganizado modularmente en src/UI/gestion/ para máxima mantenibilidad.
"""
from src.UI.gestion import VentanaGestion, ruta_recurso, _migrar_bd, _backfill_dias

__all__ = ['VentanaGestion', 'ruta_recurso', '_migrar_bd', '_backfill_dias']
