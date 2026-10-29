# -*- coding: utf-8 -*-
"""
Gestor de Iconos para SAGA (Tabler Icons - Licencia MIT)
Carga, tiñe, reescala y mantiene en caché referencias de ImageTk.PhotoImage
compatible con desarrollo local y ejecutables de PyInstaller (_MEIPASS).
"""

import os
import sys
from PIL import Image, ImageTk

def ruta_recurso(relative_path):
    """Retorna la ruta absoluta del recurso para dev y PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_path, relative_path)

class IconManager:
    _cache = {}

    # Paleta de colores predefinida
    PALETA = {
        "dark": (30, 41, 59),      # #1e293b Slate 800 - Óptimo para botones claros
        "primary": (37, 99, 235),  # #2563eb Blue 600 - Acciones principales
        "white": (255, 255, 255),  # #ffffff - Para fondos oscuros o botones Danger
        "success": (22, 163, 74),  # #16a34a Green 600
        "danger": (220, 38, 38),   # #dc2626 Red 600
    }

    @classmethod
    def get(cls, name: str, size: int = 20, color: str = "dark") -> ImageTk.PhotoImage:
        """
        Retorna un PhotoImage en caché listo para botones ttk / menús.
        Por defecto genera iconos 'dark' (#1e293b) para máximo contraste en botones claros.
        """
        key = (name, size, color)
        if key in cls._cache:
            return cls._cache[key]

        # 1. Intentar archivo pre-renderizado exacto: ej. bolt_dark_20.png
        filename = f"{name}_{color}_{size}.png"
        path = ruta_recurso(os.path.join("assets", "icons", filename))

        # 2. Si no existe, buscar archivo base para reescalar/teñir
        if not os.path.exists(path):
            for candidata in (f"{name}_dark.png", f"{name}_white_20.png", f"{name}_white_16.png"):
                p_candidata = ruta_recurso(os.path.join("assets", "icons", candidata))
                if os.path.exists(p_candidata):
                    path = p_candidata
                    break

        if not os.path.exists(path):
            return None

        try:
            with Image.open(path) as img:
                img_rgba = img.convert("RGBA")
                if img_rgba.size != (size, size):
                    img_rgba = img_rgba.resize((size, size), Image.Resampling.LANCZOS)
                
                # Determinar color RGB objetivo
                if color in cls.PALETA:
                    rgb = cls.PALETA[color]
                elif isinstance(color, str) and color.startswith("#") and len(color) == 7:
                    rgb = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
                else:
                    rgb = cls.PALETA["dark"]

                # Teñir preservando canal alpha
                alpha = img_rgba.split()[-1]
                tinted = Image.new("RGBA", (size, size), (*rgb, 255))
                tinted.putalpha(alpha)

                photo = ImageTk.PhotoImage(tinted)
                cls._cache[key] = photo
                return photo
        except Exception as e:
            print(f"Aviso IconManager: Error al cargar '{name}': {e}")
            return None
