# -*- coding: utf-8 -*-
"""
Módulo de Generación de Reportes y Sábanas Oficiales (SAGA 2.0 - UAEMéx)
Genera reportes ejecutivos en Excel y PDF con identidad institucional UAEMéx:
- Colores oficiales: Verde #385F27 y Dorado
- Escudos oficiales: Escudo UAEMéx y Logo Centro Universitario Tianguistenco
- Formatos: Sábana Matricial, Cédula de Carga Horaria Docente con Firmas,
  Horarios por Grupo de Alumnos y Cédulas de Aula/Laboratorio.
- Prevención de solapamiento de texto y auto-ajuste vertical en celdas.
"""

import datetime
import os
import sys
import sqlite3
import unicodedata
from src.conexion import obtener_cursor

def _ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base_path, relative_path)

class GeneradorSabana:
    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    HORAS = [f"{h:02d}:00" for h in range(7, 18)]
    FRANJAS_30MIN = [
        ("07:00", "07:30"), ("07:30", "08:00"),
        ("08:00", "08:30"), ("08:30", "09:00"),
        ("09:00", "09:30"), ("09:30", "10:00"),
        ("10:00", "10:30"), ("10:30", "11:00"),
        ("11:00", "11:30"), ("11:30", "12:00"),
        ("12:00", "12:30"), ("12:30", "13:00"),
        ("13:00", "13:30"), ("13:30", "14:00"),
        ("14:00", "14:30"), ("14:30", "15:00"),
        ("15:00", "15:30"), ("15:30", "16:00"),
        ("16:00", "16:30"), ("16:30", "17:00")
    ]

    # Identidad Institucional UAEMéx
    HEX_VERDE_UAEMEX = "385F27"      # #385F27 Verde UAEMéx
    HEX_VERDE_OSCURO = "25401A"      # Verde institucional profundo
    HEX_VERDE_BG_CLARO = "E8F5E9"    # Fondo tenue para clases activas
    HEX_VERDE_TEXTO = "1B4315"       # Texto de alta legibilidad sobre verde claro
    HEX_BORDE = "A3CF9D"

    @classmethod
    def _abreviar_materia(cls, nombre, max_lineas=2, max_ancho=16):
        """
        Abrevia términos comunes y aplica salto de línea para que los textos
        encajen estéticamente dentro de las celdas de horarios sin desbordarse.
        """
        import textwrap
        if not nombre:
            return ""
        nombre = str(nombre).strip()
        
        abreviaturas = {
            'ADMINISTRACION': 'ADMIN.', 'ADMINISTRACIÓN': 'ADMIN.',
            'ORGANIZACIONAL': 'ORG.', 'INVESTIGACION': 'INV.', 'INVESTIGACIÓN': 'INV.',
            'INGENIERIA': 'ING.', 'INGENIERÍA': 'ING.',
            'METODOLOGIA': 'METOD.', 'METODOLOGÍA': 'METOD.',
            'ESTADISTICA': 'ESTAD.', 'ESTADÍSTICA': 'ESTAD.',
            'ESTRUCTURAS': 'ESTR.', 'ESTRUCTURA': 'ESTR.',
            'PROGRAMACION': 'PROG.', 'PROGRAMACIÓN': 'PROG.',
            'COMPUTACION': 'COMP.', 'COMPUTACIÓN': 'COMP.',
            'COMUNICACION': 'COMUN.', 'COMUNICACIÓN': 'COMUN.',
            'TECNOLOGIAS': 'TEC.', 'TECNOLOGÍAS': 'TEC.',
            'TECNOLOGIA': 'TEC.', 'TECNOLOGÍA': 'TEC.',
            'INFORMACION': 'INFO.', 'INFORMACIÓN': 'INFO.',
            'INTELIGENCIA': 'INTEL.', 'ARTIFICIAL': 'ARTIF.',
            'CONTABILIDAD': 'CONTAB.', 'FUNDAMENTOS': 'FUND.',
            'MATEMATICAS': 'MATEM.', 'MATEMÁTICAS': 'MATEM.',
            'MATEMATICA': 'MATEM.', 'MATEMÁTICA': 'MATEM.',
            'ARQUITECTURA': 'ARQ.', 'SISTEMAS': 'SIST.',
            'OPERATIVOS': 'OPER.', 'DISTRIBUIDOS': 'DISTRIB.',
            'DESARROLLO': 'DESARR.', 'APLICACIONES': 'APLIC.',
            'PROFESIONAL': 'PROF.', 'INTERACCION': 'INTERACC.',
            'INTERACCIÓN': 'INTERACC.', 'HUMANO': 'HUM.',
            'COMPUTADORA': 'COMP.', 'COMPUTADORAS': 'COMP.',
            'FINANCIERA': 'FINANC.', 'FINANZAS': 'FINANZ.',
            'PROBABILIDAD': 'PROBAB.', 'ELECTRICA': 'ELEC.',
            'ELÉCTRICA': 'ELEC.', 'ELECTRONICA': 'ELECTR.',
            'ELECTRÓNICA': 'ELECTR.', 'CONFIANZA': 'CONF.',
            'RESPONSABILIDAD': 'RESP.',
            'LABORATORIO': 'LAB.', 'TALLER': 'TALL.',
            'INTRODUCCION': 'INTROD.', 'INTRODUCCIÓN': 'INTROD.',
            'AVANZADA': 'AVANZ.', 'AVANZADAS': 'AVANZ.',
            'AVANZADO': 'AVANZ.', 'AVANZADOS': 'AVANZ.',
            'APLICADA': 'APLIC.', 'APLICADAS': 'APLIC.',
            'APLICADO': 'APLIC.', 'APLICADOS': 'APLIC.',
            'DISPOSITIVOS': 'DISP.', 'MOVILES': 'MÓV.',
            'MÓVILES': 'MÓV.', 'BASES': 'BD', 'DATOS': 'DATOS'
        }
        
        palabras = nombre.split()
        if len(nombre) > max_ancho:
            palabras_abrev = [abreviaturas.get(p.upper(), p) for p in palabras]
            texto = ' '.join(palabras_abrev)
        else:
            texto = nombre
            
        lineas = textwrap.wrap(texto, width=max_ancho, break_long_words=True)
        if len(lineas) > max_lineas:
            lineas = lineas[:max_lineas]
            if len(lineas[-1]) > max_ancho - 2:
                lineas[-1] = lineas[-1][:max_ancho - 2] + '..'
            else:
                lineas[-1] = lineas[-1] + '..'
        return '\n'.join(lineas)

    @classmethod
    def _rutas_logos(cls):
        ruta_escudo = _ruta_recurso(os.path.join("assets", "logos", "escudo_uaemex.png"))
        ruta_campus = _ruta_recurso(os.path.join("assets", "logos", "logo_tianguistenco.png"))
        return ruta_escudo, ruta_campus

    @staticmethod
    def _normalizar_dia(dia):
        s = unicodedata.normalize('NFKD', str(dia)).encode('ascii', 'ignore').decode('ascii').strip().lower()
        mapa = {"lunes": "Lunes", "martes": "Martes", "miercoles": "Miércoles", "jueves": "Jueves", "viernes": "Viernes", "sabado": "Sábado"}
        return mapa.get(s, str(dia).strip().capitalize())

    @staticmethod
    def _formatear_hora(h):
        if isinstance(h, datetime.timedelta):
            total_sec = int(h.total_seconds())
            hh = total_sec // 3600
            mm = (total_sec % 3600) // 60
            return f"{hh:02d}:{mm:02d}"
        if isinstance(h, datetime.time):
            return f"{h.hour:02d}:{h.minute:02d}"
        partes = str(h).split(":")
        try:
            return f"{int(partes[0]):02d}:{int(partes[1]):02d}"
        except (ValueError, IndexError):
            return str(h)[:5]

    @classmethod
    def _hora_a_minutos(cls, h_str):
        partes = str(h_str).split(":")
        try:
            return int(partes[0]) * 60 + int(partes[1])
        except (ValueError, IndexError):
            return 0

    @classmethod
    def obtener_datos(cls, filtro_semestre=None, filtro_periodo=None):
        with obtener_cursor() as ctx:
            if not ctx:
                return {}
            cur, conn = ctx
            cur.execute("""
                SELECT 
                    IFNULL(g.nivel, '1') AS semestre_id,
                    a.grupo_id,
                    a.asignacion_id,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(p.nombre, 'Sin profesor') AS profesor_nombre,
                    IFNULL(h.salon_id, 'Sin aula') AS salon_id,
                    h.dia,
                    h.hora_inicio,
                    h.hora_fin,
                    a.modalidad,
                    a.periodo
                FROM asignaciones a
                JOIN horarios h ON a.asignacion_id = h.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                LEFT JOIN grupos g ON a.grupo_id = g.grupo_id
                WHERE (a.estado IS NULL OR a.estado != 'cancelada')
                ORDER BY semestre_id, a.grupo_id, h.dia, h.hora_inicio
            """)
            filas = cur.fetchall()

        datos = {}
        for r in filas:
            sem_id = str(r[0])
            g_id = str(r[1])
            if filtro_semestre and filtro_semestre != "Todos" and sem_id != str(filtro_semestre):
                continue
            periodo_asig = r[11]
            if filtro_periodo and filtro_periodo != "Todos":
                if periodo_asig and str(periodo_asig).strip() != str(filtro_periodo).strip():
                    continue

            dia_norm = cls._normalizar_dia(r[7])
            h_ini_str = cls._formatear_hora(r[8])
            h_fin_str = cls._formatear_hora(r[9])

            if sem_id not in datos:
                datos[sem_id] = {"grupos": {}}
            if g_id not in datos[sem_id]["grupos"]:
                datos[sem_id]["grupos"][g_id] = []

            datos[sem_id]["grupos"][g_id].append({
                "asignacion_id": r[2],
                "materia_id": r[3],
                "materia_nombre": r[4],
                "profesor_nombre": r[5],
                "salon_id": r[6],
                "dia": dia_norm,
                "hora_inicio": h_ini_str,
                "hora_fin": h_fin_str,
                "ini_min": cls._hora_a_minutos(h_ini_str),
                "fin_min": cls._hora_a_minutos(h_fin_str),
                "modalidad": r[10]
            })

        return datos

    # =========================================================================
    # 1. EXCEL SÁBANA OFICIAL (CON LOGOS, VERDE #385F27 Y AJUSTE VERTICAL)
    # =========================================================================

    @classmethod
    def generar_excel_sabana(cls, ruta_archivo, filtro_semestre=None, filtro_periodo=None):
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
            from openpyxl.drawing.image import Image as OpenpyxlImage
        except ImportError:
            return {"exito": False, "mensaje": "Se requiere la librería 'openpyxl' para exportar a Excel."}

        datos = cls.obtener_datos(filtro_semestre, filtro_periodo)
        if not datos:
            return {"exito": False, "mensaje": "No se encontraron asignaciones para los filtros seleccionados."}

        ruta_escudo, ruta_campus = cls._rutas_logos()

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        font_inst = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_titulo = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
        font_sub = Font(name="Calibri", size=9, color="F0FDF4")
        font_hdr = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        font_dia = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_hora = Font(name="Calibri", size=9, bold=True, color="1E293B")
        font_clase = Font(name="Calibri", size=9, bold=True, color=cls.HEX_VERDE_TEXTO)

        fill_inst = PatternFill(start_color=cls.HEX_VERDE_OSCURO, end_color=cls.HEX_VERDE_OSCURO, fill_type="solid")
        fill_titulo = PatternFill(start_color=cls.HEX_VERDE_UAEMEX, end_color=cls.HEX_VERDE_UAEMEX, fill_type="solid")
        fill_dia = PatternFill(start_color=cls.HEX_VERDE_OSCURO, end_color=cls.HEX_VERDE_OSCURO, fill_type="solid")
        fill_hora = PatternFill(start_color="F8FAF6", end_color="F8FAF6", fill_type="solid")
        fill_clase = PatternFill(start_color=cls.HEX_VERDE_BG_CLARO, end_color=cls.HEX_VERDE_BG_CLARO, fill_type="solid")

        side_borde = Side(style='thin', color=cls.HEX_BORDE)
        border_clase = Border(left=side_borde, right=side_borde, top=side_borde, bottom=side_borde)
        border_std = Border(left=Side(style='thin', color='CBD5E1'), right=Side(style='thin', color='CBD5E1'), top=Side(style='thin', color='CBD5E1'), bottom=Side(style='thin', color='CBD5E1'))

        # ALINEACIÓN QUE ENVUELVE EL TEXTO HACIA ABAJO (NO SE EXTIENDE HORIZONTALMENTE)
        align_wrap_center = Alignment(horizontal='center', vertical='center', wrap_text=True)

        total_grupos_exportados = 0

        for sem_id, sem_data in sorted(datos.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 99):
            grupos_dict = sem_data["grupos"]
            lista_grupos = sorted(grupos_dict.keys())
            if not lista_grupos:
                continue

            total_grupos_exportados += len(lista_grupos)
            nombre_hoja = f"Semestre {sem_id}"[:31]
            ws = wb.create_sheet(title=nombre_hoja)
            ws.views.sheetView[0].showGridLines = True

            total_cols = 2 + len(lista_grupos)

            # Fila 1: Encabezado Institucional
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
            c1 = ws.cell(row=1, column=1, value="UNIVERSIDAD AUTÓNOMA DEL ESTADO DE MÉXICO - CENTRO UNIVERSITARIO UAEM TIANGUISTENCO")
            c1.font = font_inst
            c1.fill = fill_inst
            c1.alignment = align_wrap_center
            ws.row_dimensions[1].height = 26

            # Fila 2: Título Sábana
            periodo_txt = f" - Periodo {filtro_periodo}" if filtro_periodo else ""
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_cols)
            c2 = ws.cell(row=2, column=1, value=f"SÁBANA MATRICIAL CONSOLIDADA - SEMESTRE {sem_id}{periodo_txt}")
            c2.font = font_titulo
            c2.fill = fill_titulo
            c2.alignment = align_wrap_center
            ws.row_dimensions[2].height = 28

            # Fila 3: Subtítulo
            ahora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
            ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=total_cols)
            c3 = ws.cell(row=3, column=1, value=f"Fecha de Emisión: {ahora}   |   Total de Grupos: {len(lista_grupos)}   |   SAGA 2.0")
            c3.font = font_sub
            c3.fill = PatternFill(start_color="2A471D", end_color="2A471D", fill_type="solid")
            c3.alignment = align_wrap_center
            ws.row_dimensions[3].height = 20

            # Añadir Escudos en esquinas
            if os.path.exists(ruta_escudo):
                try:
                    img_esc = OpenpyxlImage(ruta_escudo)
                    img_esc.width = 65
                    img_esc.height = 65
                    ws.add_image(img_esc, "A1")
                except Exception:
                    pass

            if os.path.exists(ruta_campus):
                try:
                    img_cam = OpenpyxlImage(ruta_campus)
                    img_cam.width = 110
                    img_cam.height = 50
                    col_let = get_column_letter(total_cols)
                    ws.add_image(img_cam, f"{col_let}1")
                except Exception:
                    pass

            # Fila 4: Encabezados de Columnas
            ws.cell(row=4, column=1, value="DÍA").font = font_hdr
            ws.cell(row=4, column=1).fill = fill_dia
            ws.cell(row=4, column=1).alignment = align_wrap_center
            ws.cell(row=4, column=1).border = border_std

            ws.cell(row=4, column=2, value="HORARIO").font = font_hdr
            ws.cell(row=4, column=2).fill = fill_dia
            ws.cell(row=4, column=2).alignment = align_wrap_center
            ws.cell(row=4, column=2).border = border_std

            for col_idx, g_id in enumerate(lista_grupos, start=3):
                c_g = ws.cell(row=4, column=col_idx, value=f"GRUPO {g_id}")
                c_g.font = font_hdr
                c_g.fill = fill_titulo
                c_g.alignment = align_wrap_center
                c_g.border = border_std

            ws.row_dimensions[4].height = 24

            franjas = cls.FRANJAS_30MIN
            fila_actual = 5

            for dia in cls.DIAS:
                fila_inicio_dia = fila_actual
                col_data = {c_i: {} for c_i in range(3, 3 + len(lista_grupos))}

                for h_ini_f, h_fin_f in franjas:
                    f_ini_min = cls._hora_a_minutos(h_ini_f)
                    f_fin_min = cls._hora_a_minutos(h_fin_f)

                    c_h = ws.cell(row=fila_actual, column=2, value=f"{h_ini_f} - {h_fin_f}")
                    c_h.font = font_hora
                    c_h.fill = fill_hora
                    c_h.alignment = align_wrap_center
                    c_h.border = border_std
                    ws.row_dimensions[fila_actual].height = 22

                    for col_idx, g_id in enumerate(lista_grupos, start=3):
                        sesiones_grupo = grupos_dict.get(g_id, [])
                        coinc = [
                            s for s in sesiones_grupo
                            if s['dia'] == dia and s['ini_min'] < f_fin_min and s['fin_min'] > f_ini_min
                        ]
                        if coinc:
                            s = coinc[0]
                            mod_str = str(s.get('modalidad', '')).lower()
                            modal_txt = " [MT]" if ('mediacion' in mod_str or 'linea' in mod_str) else ""
                            txt = f"{s['materia_nombre']}\nProf: {s['profesor_nombre']}\nAula: {s['salon_id']}{modal_txt}"
                            col_data[col_idx][fila_actual] = (s['asignacion_id'], txt)
                        else:
                            col_data[col_idx][fila_actual] = None

                    fila_actual += 1

                fila_fin_dia = fila_actual - 1

                # Combinar verticalmente las celdas continuas de la misma clase por columna
                for col_idx in range(3, 3 + len(lista_grupos)):
                    r_ptr = fila_inicio_dia
                    while r_ptr <= fila_fin_dia:
                        info = col_data[col_idx].get(r_ptr)
                        if info is None:
                            c = ws.cell(row=r_ptr, column=col_idx, value="")
                            c.border = border_std
                            r_ptr += 1
                        else:
                            asig_id, txt = info
                            r_start = r_ptr
                            while r_ptr + 1 <= fila_fin_dia and col_data[col_idx].get(r_ptr + 1) and col_data[col_idx][r_ptr + 1][0] == asig_id:
                                r_ptr += 1
                            r_end = r_ptr

                            if r_end > r_start:
                                ws.merge_cells(start_row=r_start, start_column=col_idx, end_row=r_end, end_column=col_idx)

                            for row_cell in range(r_start, r_end + 1):
                                cell_item = ws.cell(row=row_cell, column=col_idx)
                                cell_item.border = border_clase
                                cell_item.fill = fill_clase

                            top_cell = ws.cell(row=r_start, column=col_idx, value=txt)
                            top_cell.font = font_clase
                            top_cell.alignment = align_wrap_center # Ajuste vertical hacia abajo

                            r_ptr += 1

                # Combinar columna de Día
                ws.merge_cells(start_row=fila_inicio_dia, start_column=1, end_row=fila_fin_dia, end_column=1)
                c_dia = ws.cell(row=fila_inicio_dia, column=1, value=dia.upper())
                c_dia.font = font_dia
                c_dia.fill = fill_dia
                c_dia.alignment = align_wrap_center
                for r_d in range(fila_inicio_dia, fila_fin_dia + 1):
                    ws.cell(row=r_d, column=1).border = border_std

            # Anchos acotados para forzar el flujo vertical del texto
            ws.column_dimensions['A'].width = 12
            ws.column_dimensions['B'].width = 14
            for col_idx in range(3, 3 + len(lista_grupos)):
                col_letter = get_column_letter(col_idx)
                ws.column_dimensions[col_letter].width = 22 # Compacto y ordenado

        wb.save(ruta_archivo)
        return {
            "exito": True,
            "ruta": ruta_archivo,
            "total_semestres": len(datos),
            "total_grupos": total_grupos_exportados
        }

    # =========================================================================
    # 2. SÁBANA MATRICIAL PDF (SIN COLISIÓN DE TEXTO, LOGOS Y VERDE #385F27)
    # =========================================================================

    @classmethod
    def generar_pdf_sabana(cls, ruta_archivo, filtro_semestre=None, filtro_periodo=None):
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        from PIL import Image

        datos = cls.obtener_datos(filtro_semestre, filtro_periodo)
        if not datos:
            return {"exito": False, "mensaje": "No se encontraron asignaciones para los filtros seleccionados."}

        ruta_escudo, ruta_campus = cls._rutas_logos()
        img_escudo = Image.open(ruta_escudo) if os.path.exists(ruta_escudo) else None
        img_campus = Image.open(ruta_campus) if os.path.exists(ruta_campus) else None

        franjas = cls.FRANJAS_30MIN

        with PdfPages(ruta_archivo) as pdf:
            for sem_id, sem_data in sorted(datos.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 99):
                grupos_dict = sem_data["grupos"]
                lista_grupos = sorted(grupos_dict.keys())
                if not lista_grupos:
                    continue

                for dia in cls.DIAS:
                    fig = plt.figure(figsize=(16, 11), facecolor='#FFFFFF')

                    # Escudos institucionales en esquinas superiores
                    if img_escudo:
                        ax_esc = fig.add_axes([0.03, 0.88, 0.07, 0.10])
                        ax_esc.imshow(img_escudo)
                        ax_esc.axis('off')

                    if img_campus:
                        ax_cam = fig.add_axes([0.88, 0.89, 0.09, 0.08])
                        ax_cam.imshow(img_campus)
                        ax_cam.axis('off')

                    periodo_txt = f" (Periodo {filtro_periodo})" if filtro_periodo else ""
                    fig.text(0.5, 0.96, "UNIVERSIDAD AUTÓNOMA DEL ESTADO DE MÉXICO", ha='center', fontsize=12, fontweight='bold', color='#1A3311')
                    fig.text(0.5, 0.93, "CENTRO UNIVERSITARIO UAEM TIANGUISTENCO", ha='center', fontsize=10, fontweight='bold', color='#4A5568')
                    fig.text(0.5, 0.89, f"SÁBANA MATRICIAL CONSOLIDADA - SEMESTRE {sem_id}{periodo_txt} - {dia.upper()}", ha='center', fontsize=15, fontweight='bold', color=f"#{cls.HEX_VERDE_UAEMEX}")

                    ax_tab = fig.add_axes([0.04, 0.04, 0.92, 0.82])
                    ax_tab.axis('tight')
                    ax_tab.axis('off')

                    columnas = ['Día', 'Horario'] + [f"Gpo {g}" for g in lista_grupos]
                    filas_tabla = []

                    # PREVENCIÓN DE SOLAPAMIENTO: Distribución limpia en bloques
                    for f_idx, (h_ini_f, h_fin_f) in enumerate(franjas):
                        f_ini_min = cls._hora_a_minutos(h_ini_f)
                        f_fin_min = cls._hora_a_minutos(h_fin_f)
                        fila = [dia, f"{h_ini_f} - {h_fin_f}"]

                        for g_id in lista_grupos:
                            sesiones_grupo = grupos_dict.get(g_id, [])
                            coinc = [
                                s for s in sesiones_grupo
                                if s['dia'] == dia and s['ini_min'] < f_fin_min and s['fin_min'] > f_ini_min
                            ]
                            if coinc:
                                s = coinc[0]
                                es_primer_slot = (f_ini_min == s['ini_min']) or (f_idx == 0 and s['ini_min'] < f_ini_min)
                                es_segundo_slot = (f_ini_min == s['ini_min'] + 30)

                                mod_str = str(s.get('modalidad', '')).lower()
                                modal_txt = " [MT]" if ('mediacion' in mod_str or 'linea' in mod_str) else ""
                                dur_min = s['fin_min'] - s['ini_min']

                                if dur_min <= 30:
                                    txt = f"{cls._abreviar_materia(s['materia_nombre'], max_lineas=1, max_ancho=16)}\nAula: {s['salon_id']}"
                                elif es_primer_slot:
                                    # Slot 1: Materia y horario
                                    txt = f"{cls._abreviar_materia(s['materia_nombre'], max_lineas=2, max_ancho=16)}\n({s['hora_inicio']} - {s['hora_fin']})"
                                elif es_segundo_slot:
                                    # Slot 2: Profesor y aula
                                    txt = f"Prof: {s['profesor_nombre'][:18]}\nAula: {s['salon_id']}{modal_txt}"
                                else:
                                    # Slot 3+: Bloque iluminado sin saturar de texto
                                    txt = ""
                                fila.append(txt)
                            else:
                                fila.append("-")
                        filas_tabla.append(fila)

                    tab = ax_tab.table(
                        cellText=filas_tabla,
                        colLabels=columnas,
                        loc='center',
                        cellLoc='center'
                    )
                    tab.auto_set_font_size(False)
                    tab.set_fontsize(6.5)
                    tab.scale(1.0, 1.45)

                    # Encabezados con Verde #385F27
                    for c_i in range(len(columnas)):
                        cell = tab[(0, c_i)]
                        cell.set_facecolor(f"#{cls.HEX_VERDE_UAEMEX}")
                        cell.set_text_props(color='white', weight='bold')

                    # Celdas con clase en verde suave #E8F5E9
                    for r_i, r_data in enumerate(filas_tabla, start=1):
                        for c_i in range(len(columnas)):
                            cell = tab[(r_i, c_i)]
                            val_txt = r_data[c_i]
                            if c_i < 2:
                                cell.set_facecolor('#F8FAF6')
                                cell.set_text_props(weight='bold', color='#2D3748')
                            elif val_txt != "-":
                                cell.set_facecolor(f"#{cls.HEX_VERDE_BG_CLARO}")
                                cell.set_text_props(color=f"#{cls.HEX_VERDE_TEXTO}", weight='bold')
                            else:
                                cell.set_facecolor('#FFFFFF')
                                cell.set_text_props(color='#CBD5E1')

                    pdf.savefig(fig, bbox_inches='tight', dpi=150)
                    plt.close(fig)

        return {
            "exito": True,
            "ruta": ruta_archivo,
            "total_semestres": len(datos)
        }

    # =========================================================================
    # 3. CÉDULA DE CARGA HORARIA DOCENTE CON FIRMAS (PDF UAEMéx)
    # =========================================================================

    @classmethod
    def generar_pdf_fichas_profesores(cls, ruta_archivo, filtro_profesor_id=None, filtro_periodo=None):
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        from PIL import Image

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "Sin conexión a base de datos."}
            cur, conn = ctx

            condiciones = ["(a.estado IS NULL OR a.estado != 'cancelada')"]
            params = []
            if filtro_profesor_id:
                condiciones.append("p.profesor_id = %s")
                params.append(filtro_profesor_id)
            if filtro_periodo and filtro_periodo != "Todos":
                condiciones.append("a.periodo = %s")
                params.append(filtro_periodo)

            cur.execute(f"""
                SELECT 
                    p.profesor_id,
                    IFNULL(p.no_cuenta, 'S/N') AS no_cuenta,
                    p.nombre AS profesor_nombre,
                    a.grupo_id,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(h.salon_id, 'Sin aula') AS salon_id,
                    h.dia,
                    h.hora_inicio,
                    h.hora_fin,
                    IFNULL(a.modalidad, 'Presencial') AS modalidad,
                    a.periodo
                FROM profesores p
                JOIN asignaciones a ON p.profesor_id = a.profesor_id
                JOIN horarios h ON a.asignacion_id = h.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                WHERE {" AND ".join(condiciones)}
                ORDER BY p.nombre, h.dia, h.hora_inicio
            """, tuple(params))
            filas = cur.fetchall()

        if not filas:
            return {"exito": False, "mensaje": "No se encontraron asignaciones de profesores para exportar."}

        profesores_dict = {}
        for r in filas:
            pid = r[0]
            if pid not in profesores_dict:
                profesores_dict[pid] = {
                    "id": pid,
                    "cuenta": r[1],
                    "nombre": r[2],
                    "sesiones": [],
                    "horas_totales": 0.0
                }
            h_i = cls._formatear_hora(r[8])
            h_f = cls._formatear_hora(r[9])
            ini_min = cls._hora_a_minutos(h_i)
            fin_min = cls._hora_a_minutos(h_f)
            profesores_dict[pid]["horas_totales"] += (fin_min - ini_min) / 60.0
            profesores_dict[pid]["sesiones"].append({
                "grupo": r[3],
                "materia": r[5],
                "salon": r[6],
                "dia": cls._normalizar_dia(r[7]),
                "hora_i": h_i,
                "hora_f": h_f,
                "ini_min": ini_min,
                "fin_min": fin_min,
                "modalidad": r[10]
            })

        ruta_escudo, ruta_campus = cls._rutas_logos()
        img_escudo = Image.open(ruta_escudo) if os.path.exists(ruta_escudo) else None
        img_campus = Image.open(ruta_campus) if os.path.exists(ruta_campus) else None

        horas_filas = [f"{h:02d}:00 - {h+1:02d}:00" for h in range(7, 18)]
        dias_cols = ["Horario", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

        with PdfPages(ruta_archivo) as pdf:
            for pid, pdata in sorted(profesores_dict.items(), key=lambda x: x[1]["nombre"]):
                fig = plt.figure(figsize=(11.69, 8.27), facecolor='#FFFFFF')

                if img_escudo:
                    ax_esc = fig.add_axes([0.03, 0.865, 0.08, 0.11])
                    ax_esc.imshow(img_escudo)
                    ax_esc.axis('off')

                if img_campus:
                    ax_cam = fig.add_axes([0.84, 0.875, 0.13, 0.09])
                    ax_cam.imshow(img_campus)
                    ax_cam.axis('off')

                fig.text(0.5, 0.965, "UNIVERSIDAD AUTÓNOMA DEL ESTADO DE MÉXICO", ha='center', fontsize=11, fontweight='bold', color='#1A3311')
                fig.text(0.5, 0.932, "CENTRO UNIVERSITARIO UAEM TIANGUISTENCO", ha='center', fontsize=9.5, fontweight='bold', color='#4A5568')
                fig.text(0.5, 0.892, "CÉDULA DE CARGA HORARIA DOCENTE INDIVIDUAL", ha='center', fontsize=14, fontweight='bold', color=f"#{cls.HEX_VERDE_UAEMEX}")

                info_txt = f"Docente: {pdata['nombre']}    |    No. Cuenta: {pdata['cuenta']}    |    Total Horas Semanales: {pdata['horas_totales']:.1f} hrs"
                if filtro_periodo and filtro_periodo != "Todos":
                    info_txt += f"    |    Período: {filtro_periodo}"
                fig.text(0.5, 0.855, info_txt, ha='center', fontsize=9.5, fontweight='bold', color='#2D3748')

                # Tabla extendida hacia arriba para maximizar el espacio sin afectar firmas
                ax = fig.add_axes([0.03, 0.13, 0.94, 0.70])
                ax.axis('tight')
                ax.axis('off')

                tabla_datos = []
                for h_idx, h_str in enumerate(horas_filas):
                    h_num = 7 + h_idx
                    min_start = h_num * 60
                    min_end = (h_num + 1) * 60
                    fila = [h_str]

                    for dia in dias_cols[1:]:
                        coinc = [
                            s for s in pdata["sesiones"]
                            if s["dia"] == dia and s["ini_min"] < min_end and s["fin_min"] > min_start
                        ]
                        if coinc:
                            s = coinc[0]
                            mat_fmt = cls._abreviar_materia(s['materia'], max_lineas=2, max_ancho=16)
                            fila.append(f"{mat_fmt}\nGrupo: {s['grupo']} | Aula: {s['salon']}")
                        else:
                            fila.append("")
                    tabla_datos.append(fila)

                tabla = ax.table(cellText=tabla_datos, colLabels=dias_cols, loc='center', cellLoc='center', bbox=[0, 0, 1, 1])
                tabla.auto_set_font_size(False)
                tabla.set_fontsize(8.5)

                for c_i in range(len(dias_cols)):
                    cell = tabla[(0, c_i)]
                    cell.set_facecolor(f"#{cls.HEX_VERDE_UAEMEX}")
                    cell.set_text_props(color='white', weight='bold')

                for r_i, r_data in enumerate(tabla_datos, start=1):
                    for c_i in range(len(dias_cols)):
                        cell = tabla[(r_i, c_i)]
                        texto = r_data[c_i]
                        if c_i == 0:
                            cell.set_facecolor('#F8FAF6')
                            cell.set_text_props(weight='bold', color='#2D3748', fontsize=8)
                        elif texto:
                            cell.set_facecolor(f"#{cls.HEX_VERDE_BG_CLARO}")
                            lineas = texto.split('\n')
                            max_len = max(len(l) for l in lineas)
                            num_lineas = len(lineas)
                            if max_len > 18 or num_lineas >= 4:
                                tam_fuente = 6.2
                            elif max_len > 13 or num_lineas >= 3:
                                tam_fuente = 7.0
                            else:
                                tam_fuente = 7.8
                            cell.set_text_props(color=f"#{cls.HEX_VERDE_TEXTO}", weight='bold', fontsize=tam_fuente)
                        else:
                            cell.set_facecolor('#FFFFFF')

                fig.text(0.25, 0.065, "_________________________________________\nFirma del Docente", ha='center', fontsize=9, color='#334155')
                fig.text(0.75, 0.065, "_________________________________________\nJefatura de División Académica", ha='center', fontsize=9, color='#334155')
                fig.text(0.95, 0.015, f"Generado: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", ha='right', fontsize=7, color='#94A3B8')

                pdf.savefig(fig, bbox_inches='tight', dpi=150)
                plt.close(fig)

        return {"exito": True, "ruta": ruta_archivo, "total_profesores": len(profesores_dict)}

    # =========================================================================
    # 4. HORARIO POR GRUPO DE ALUMNOS (PDF UAEMéx)
    # =========================================================================

    @classmethod
    def generar_pdf_fichas_grupos(cls, ruta_archivo, filtro_semestre=None, filtro_periodo=None):
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        from PIL import Image

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "Sin conexión a base de datos."}
            cur, conn = ctx

            condiciones = ["(a.estado IS NULL OR a.estado != 'cancelada')"]
            params = []
            if filtro_semestre and filtro_semestre != "Todos":
                condiciones.append("g.nivel = %s")
                params.append(filtro_semestre)
            if filtro_periodo and filtro_periodo != "Todos":
                condiciones.append("a.periodo = %s")
                params.append(filtro_periodo)

            cur.execute(f"""
                SELECT 
                    a.grupo_id,
                    IFNULL(g.nivel, '1') AS nivel,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(p.nombre, 'Sin profesor') AS profesor_nombre,
                    IFNULL(h.salon_id, 'Sin aula') AS salon_id,
                    h.dia,
                    h.hora_inicio,
                    h.hora_fin,
                    IFNULL(a.modalidad, 'Presencial') AS modalidad,
                    a.periodo
                FROM asignaciones a
                JOIN horarios h ON a.asignacion_id = h.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                LEFT JOIN grupos g ON a.grupo_id = g.grupo_id
                WHERE {" AND ".join(condiciones)}
                ORDER BY g.nivel, a.grupo_id, h.dia, h.hora_inicio
            """, tuple(params))
            filas = cur.fetchall()

        if not filas:
            return {"exito": False, "mensaje": "No se encontraron horarios de grupos para exportar."}

        grupos_dict = {}
        for r in filas:
            gid = r[0]
            if gid not in grupos_dict:
                grupos_dict[gid] = {
                    "grupo": gid,
                    "nivel": r[1],
                    "sesiones": [],
                    "horas_totales": 0.0
                }
            h_i = cls._formatear_hora(r[7])
            h_f = cls._formatear_hora(r[8])
            ini_min = cls._hora_a_minutos(h_i)
            fin_min = cls._hora_a_minutos(h_f)
            grupos_dict[gid]["horas_totales"] += (fin_min - ini_min) / 60.0
            grupos_dict[gid]["sesiones"].append({
                "materia": r[3],
                "profesor": r[4],
                "salon": r[5],
                "dia": cls._normalizar_dia(r[6]),
                "hora_i": h_i,
                "hora_f": h_f,
                "ini_min": ini_min,
                "fin_min": fin_min,
                "modalidad": r[9]
            })

        ruta_escudo, ruta_campus = cls._rutas_logos()
        img_escudo = Image.open(ruta_escudo) if os.path.exists(ruta_escudo) else None
        img_campus = Image.open(ruta_campus) if os.path.exists(ruta_campus) else None

        horas_filas = [f"{h:02d}:00 - {h+1:02d}:00" for h in range(7, 18)]
        dias_cols = ["Horario", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

        with PdfPages(ruta_archivo) as pdf:
            for gid, gdata in sorted(grupos_dict.items(), key=lambda x: str(x[0])):
                fig = plt.figure(figsize=(11.69, 8.27), facecolor='#FFFFFF')

                if img_escudo:
                    ax_esc = fig.add_axes([0.03, 0.865, 0.08, 0.11])
                    ax_esc.imshow(img_escudo)
                    ax_esc.axis('off')

                if img_campus:
                    ax_cam = fig.add_axes([0.84, 0.875, 0.13, 0.09])
                    ax_cam.imshow(img_campus)
                    ax_cam.axis('off')

                fig.text(0.5, 0.965, "UNIVERSIDAD AUTÓNOMA DEL ESTADO DE MÉXICO", ha='center', fontsize=11, fontweight='bold', color='#1A3311')
                fig.text(0.5, 0.932, "CENTRO UNIVERSITARIO UAEM TIANGUISTENCO", ha='center', fontsize=9.5, fontweight='bold', color='#4A5568')
                fig.text(0.5, 0.892, f"HORARIO SEMANAL DE CLASES - GRUPO {gid}", ha='center', fontsize=14, fontweight='bold', color=f"#{cls.HEX_VERDE_UAEMEX}")

                info_txt = f"Grupo: {gid}    |    Semestre: {gdata['nivel']}    |    Total Horas Semanales: {gdata['horas_totales']:.1f} hrs"
                if filtro_periodo and filtro_periodo != "Todos":
                    info_txt += f"    |    Período: {filtro_periodo}"
                fig.text(0.5, 0.855, info_txt, ha='center', fontsize=9.5, fontweight='bold', color='#2D3748')

                ax = fig.add_axes([0.03, 0.13, 0.94, 0.70])
                ax.axis('tight')
                ax.axis('off')

                tabla_datos = []
                for h_idx, h_str in enumerate(horas_filas):
                    h_num = 7 + h_idx
                    min_start = h_num * 60
                    min_end = (h_num + 1) * 60
                    fila = [h_str]

                    for dia in dias_cols[1:]:
                        coinc = [
                            s for s in gdata["sesiones"]
                            if s["dia"] == dia and s["ini_min"] < min_end and s["fin_min"] > min_start
                        ]
                        if coinc:
                            s = coinc[0]
                            mat_fmt = cls._abreviar_materia(s['materia'], max_lineas=2, max_ancho=16)
                            prof_fmt = s['profesor'].strip()
                            if len(prof_fmt) > 16:
                                partes_p = prof_fmt.split()
                                if len(partes_p) >= 3:
                                    prof_fmt = f"{partes_p[0][:4]}. {partes_p[1]} {partes_p[2][:1]}."
                                else:
                                    prof_fmt = prof_fmt[:16]
                            fila.append(f"{mat_fmt}\nAula: {s['salon']} | Prof: {prof_fmt}")
                        else:
                            fila.append("")
                    tabla_datos.append(fila)

                tabla = ax.table(cellText=tabla_datos, colLabels=dias_cols, loc='center', cellLoc='center', bbox=[0, 0, 1, 1])
                tabla.auto_set_font_size(False)
                tabla.set_fontsize(8.5)

                for c_i in range(len(dias_cols)):
                    cell = tabla[(0, c_i)]
                    cell.set_facecolor(f"#{cls.HEX_VERDE_UAEMEX}")
                    cell.set_text_props(color='white', weight='bold')

                for r_i, r_data in enumerate(tabla_datos, start=1):
                    for c_i in range(len(dias_cols)):
                        cell = tabla[(r_i, c_i)]
                        texto = r_data[c_i]
                        if c_i == 0:
                            cell.set_facecolor('#F8FAF6')
                            cell.set_text_props(weight='bold', color='#2D3748', fontsize=8)
                        elif texto:
                            cell.set_facecolor(f"#{cls.HEX_VERDE_BG_CLARO}")
                            lineas = texto.split('\n')
                            max_len = max(len(l) for l in lineas)
                            num_lineas = len(lineas)
                            if max_len > 18 or num_lineas >= 4:
                                tam_fuente = 6.2
                            elif max_len > 13 or num_lineas >= 3:
                                tam_fuente = 7.0
                            else:
                                tam_fuente = 7.8
                            cell.set_text_props(color=f"#{cls.HEX_VERDE_TEXTO}", weight='bold', fontsize=tam_fuente)
                        else:
                            cell.set_facecolor('#FFFFFF')

                fig.text(0.5, 0.065, "Nota: Los horarios oficiales están sujetos a cambios por necesidades institucionales aprobadas por la Dirección.", ha='center', fontsize=8, color='#64748B', style='italic')
                fig.text(0.95, 0.015, f"Generado: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", ha='right', fontsize=7, color='#94A3B8')

                pdf.savefig(fig, bbox_inches='tight', dpi=150)
                plt.close(fig)

        return {"exito": True, "ruta": ruta_archivo, "total_grupos": len(grupos_dict)}

    # =========================================================================
    # 5. CÉDULA DE OCUPACIÓN POR AULA / LABORATORIO (PDF UAEMéx)
    # =========================================================================

    @classmethod
    def generar_pdf_cedulas_aulas(cls, ruta_archivo, filtro_periodo=None):
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        from PIL import Image

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "Sin conexión a base de datos."}
            cur, conn = ctx

            condiciones = ["(a.estado IS NULL OR a.estado != 'cancelada')"]
            params = []
            if filtro_periodo and filtro_periodo != "Todos":
                condiciones.append("a.periodo = %s")
                params.append(filtro_periodo)

            cur.execute(f"""
                SELECT 
                    s.salon_id,
                    s.capacidad,
                    s.tipo,
                    a.grupo_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(p.nombre, 'Sin profesor') AS profesor_nombre,
                    h.dia,
                    h.hora_inicio,
                    h.hora_fin,
                    IFNULL(a.modalidad, 'Presencial') AS modalidad
                FROM salones s
                JOIN horarios h ON s.salon_id = h.salon_id
                JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                WHERE {" AND ".join(condiciones)}
                ORDER BY s.salon_id, h.dia, h.hora_inicio
            """, tuple(params))
            filas = cur.fetchall()

        if not filas:
            return {"exito": False, "mensaje": "No se encontraron asignaciones en salones para exportar."}

        ruta_escudo, ruta_campus = cls._rutas_logos()
        img_escudo = Image.open(ruta_escudo) if os.path.exists(ruta_escudo) else None
        img_campus = Image.open(ruta_campus) if os.path.exists(ruta_campus) else None

        aulas_dict = {}
        for r in filas:
            sid = r[0]
            if sid not in aulas_dict:
                aulas_dict[sid] = {
                    "id": sid,
                    "capacidad": r[1],
                    "tipo": r[2],
                    "sesiones": [],
                    "horas_ocupadas": 0.0
                }
            h_i = cls._formatear_hora(r[7])
            h_f = cls._formatear_hora(r[8])
            ini_min = cls._hora_a_minutos(h_i)
            fin_min = cls._hora_a_minutos(h_f)
            aulas_dict[sid]["horas_ocupadas"] += (fin_min - ini_min) / 60.0
            aulas_dict[sid]["sesiones"].append({
                "grupo": r[3],
                "materia": r[4],
                "profesor": r[5],
                "dia": cls._normalizar_dia(r[6]),
                "hora_i": h_i,
                "hora_f": h_f,
                "ini_min": ini_min,
                "fin_min": fin_min,
                "modalidad": r[9]
            })

        horas_filas = [f"{h:02d}:00 - {h+1:02d}:00" for h in range(7, 18)]
        dias_cols = ["Horario", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

        with PdfPages(ruta_archivo) as pdf:
            for sid, sdata in sorted(aulas_dict.items(), key=lambda x: str(x[0])):
                fig = plt.figure(figsize=(11.69, 8.27), facecolor='#FFFFFF')

                if img_escudo:
                    ax_esc = fig.add_axes([0.04, 0.85, 0.09, 0.12])
                    ax_esc.imshow(img_escudo)
                    ax_esc.axis('off')

                if img_campus:
                    ax_cam = fig.add_axes([0.83, 0.86, 0.13, 0.10])
                    ax_cam.imshow(img_campus)
                    ax_cam.axis('off')

                fig.text(0.5, 0.95, "UNIVERSIDAD AUTÓNOMA DEL ESTADO DE MÉXICO", ha='center', fontsize=12, fontweight='bold', color='#1A3311')
                fig.text(0.5, 0.91, "CENTRO UNIVERSITARIO UAEM TIANGUISTENCO", ha='center', fontsize=10, fontweight='bold', color='#4A5568')
                fig.text(0.5, 0.86, f"CÉDULA DE OCUPACIÓN SEMANAL - SALÓN: {sid}", ha='center', fontsize=15, fontweight='bold', color=f"#{cls.HEX_VERDE_UAEMEX}")

                info_txt = f"Salón: {sid}    |    Capacidad: {sdata['capacidad']} alumnos    |    Tipo: {sdata['tipo']}    |    Ocupación: {sdata['horas_ocupadas']:.1f} hrs/sem"
                fig.text(0.5, 0.82, info_txt, ha='center', fontsize=10, fontweight='bold', color='#2D3748')

                # Tabla dimensionada para aprovechar toda la hoja sin salirse
                ax = fig.add_axes([0.02, 0.05, 0.96, 0.77])
                ax.axis('tight')
                ax.axis('off')

                import textwrap
                tabla_datos = []
                for h_idx, h_str in enumerate(horas_filas):
                    h_num = 7 + h_idx
                    min_start = h_num * 60
                    min_end = (h_num + 1) * 60
                    fila = [h_str]

                    for dia in dias_cols[1:]:
                        coinc = [
                            s for s in sdata["sesiones"]
                            if s["dia"] == dia and s["ini_min"] < min_end and s["fin_min"] > min_start
                        ]
                        if coinc:
                            s = coinc[0]
                            dur_total_h = (s["fin_min"] - s["ini_min"]) / 60.0
                            hora_relativa = (min_start - s["ini_min"]) / 60.0

                            m_nom = cls._abreviar_materia(s['materia'], max_lineas=1, max_ancho=16)
                            p_nom = textwrap.shorten(s['profesor'].strip(), width=24, placeholder="..")

                            if dur_total_h > 1.0:
                                if hora_relativa < 1.0:
                                    txt_celda = f"Gpo: {s['grupo']}\n{m_nom}"
                                elif hora_relativa < 2.0:
                                    txt_celda = f"Prof: {p_nom}\n({s['hora_i']} a {s['hora_f']})"
                                else:
                                    txt_celda = "■ ■ ■"
                            else:
                                txt_celda = f"Gpo {s['grupo']} | {m_nom[:16]}\n{p_nom[:18]}"

                            fila.append(txt_celda)
                        else:
                            fila.append("")
                    tabla_datos.append(fila)

                anchos_col = [0.094] + [0.151] * 6

                tabla = ax.table(
                    cellText=tabla_datos,
                    colLabels=dias_cols,
                    colWidths=anchos_col,
                    loc='center',
                    cellLoc='center'
                )
                tabla.auto_set_font_size(False)
                tabla.set_fontsize(7.2)
                tabla.scale(1.0, 2.3)

                for c_i in range(len(dias_cols)):
                    cell = tabla[(0, c_i)]
                    cell.set_facecolor(f"#{cls.HEX_VERDE_UAEMEX}")
                    cell.set_text_props(color='white', weight='bold')

                for r_i, r_data in enumerate(tabla_datos, start=1):
                    for c_i in range(len(dias_cols)):
                        cell = tabla[(r_i, c_i)]
                        texto = r_data[c_i]
                        if c_i == 0:
                            cell.set_facecolor('#F8FAF6')
                            cell.set_text_props(weight='bold', color='#2D3748', fontsize=7.5)
                        elif texto:
                            cell.set_facecolor(f"#{cls.HEX_VERDE_BG_CLARO}")
                            lineas = texto.split('\n')
                            max_len = max(len(l) for l in lineas)
                            num_lineas = len(lineas)
                            if max_len > 18 or num_lineas >= 3:
                                tam_fuente = 6.0
                            elif max_len > 13 or num_lineas >= 2:
                                tam_fuente = 6.8
                            else:
                                tam_fuente = 7.4
                            cell.set_text_props(color=f"#{cls.HEX_VERDE_TEXTO}", weight='bold', fontsize=tam_fuente)
                        else:
                            cell.set_facecolor('#FFFFFF')

                fig.text(0.5, 0.015, "Cédula oficial para fijar en puerta de aula / laboratorio.", ha='center', fontsize=7.5, color='#64748B', style='italic')
                fig.text(0.96, 0.010, f"Generado: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", ha='right', fontsize=6.5, color='#94A3B8')

                pdf.savefig(fig, bbox_inches='tight', dpi=150)
                plt.close(fig)

        return {"exito": True, "ruta": ruta_archivo, "total_aulas": len(aulas_dict)}


    # =========================================================================
    # 6. EXPORTACIONES A EXCEL (.XLSX) OFICIALES UAEMéx
    # =========================================================================

    @classmethod
    def generar_excel_fichas_profesores(cls, ruta_archivo, filtro_profesor_id=None, filtro_periodo=None):
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "Sin conexión a base de datos."}
            cur, conn = ctx

            condiciones = ["(a.estado IS NULL OR a.estado != 'cancelada')"]
            params = []
            if filtro_profesor_id:
                condiciones.append("p.profesor_id = %s")
                params.append(filtro_profesor_id)
            if filtro_periodo and filtro_periodo != "Todos":
                condiciones.append("a.periodo = %s")
                params.append(filtro_periodo)

            cur.execute(f"""
                SELECT 
                    p.profesor_id,
                    IFNULL(p.no_cuenta, 'S/N') AS no_cuenta,
                    p.nombre AS profesor_nombre,
                    a.grupo_id,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(h.salon_id, 'Sin aula') AS salon_id,
                    h.dia,
                    h.hora_inicio,
                    h.hora_fin,
                    IFNULL(a.modalidad, 'Presencial') AS modalidad,
                    a.periodo
                FROM profesores p
                JOIN asignaciones a ON p.profesor_id = a.profesor_id
                JOIN horarios h ON a.asignacion_id = h.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                WHERE {" AND ".join(condiciones)}
                ORDER BY p.nombre, h.dia, h.hora_inicio
            """, tuple(params))
            filas = cur.fetchall()

        if not filas:
            return {"exito": False, "mensaje": "No se encontraron asignaciones de profesores para exportar."}

        profesores_dict = {}
        for r in filas:
            pid = r[0]
            if pid not in profesores_dict:
                profesores_dict[pid] = {
                    "id": pid, "cuenta": r[1], "nombre": r[2], "sesiones": [], "horas_totales": 0.0
                }
            h_i = cls._formatear_hora(r[8])
            h_f = cls._formatear_hora(r[9])
            ini_min = cls._hora_a_minutos(h_i)
            fin_min = cls._hora_a_minutos(h_f)
            profesores_dict[pid]["horas_totales"] += (fin_min - ini_min) / 60.0
            profesores_dict[pid]["sesiones"].append({
                "grupo": r[3], "materia": r[5], "salon": r[6],
                "dia": cls._normalizar_dia(r[7]),
                "hora_i": h_i, "hora_f": h_f, "ini_min": ini_min, "fin_min": fin_min,
                "modalidad": r[10]
            })

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        font_inst = Font(name="Calibri", size=11, bold=True, color="1A3311")
        font_sub = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_data = Font(name="Calibri", size=9.5, bold=True, color=cls.HEX_VERDE_TEXTO)
        font_empty = Font(name="Calibri", size=9)
        font_firma = Font(name="Calibri", size=9.5, bold=True, color="334155")

        fill_hdr = PatternFill(start_color=cls.HEX_VERDE_UAEMEX, end_color=cls.HEX_VERDE_UAEMEX, fill_type="solid")
        fill_sub = PatternFill(start_color="25401A", end_color="25401A", fill_type="solid")
        fill_slot = PatternFill(start_color=cls.HEX_VERDE_BG_CLARO, end_color=cls.HEX_VERDE_BG_CLARO, fill_type="solid")
        fill_hora = PatternFill(start_color="F8FAF6", end_color="F8FAF6", fill_type="solid")

        thin_side = Side(border_style="thin", color="A3CF9D")
        border_std = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        horas = [f"{h:02d}:00 - {h+1:02d}:00" for h in range(7, 18)]

        for pid, pdata in sorted(profesores_dict.items(), key=lambda x: x[1]["nombre"]):
            # Sanitizar nombre de hoja (max 30 chars)
            nombre_limpio = "".join(c for c in pdata["nombre"] if c.isalnum() or c in (" ", "_"))[:28].strip()
            ws = wb.create_sheet(title=nombre_limpio or f"Prof_{pid}")

            ws.merge_cells("A1:G1")
            c1 = ws["A1"]
            c1.value = "UNIVERSIDAD AUTÓNOMA DEL ESTADO DE MÉXICO - CENTRO UNIVERSITARIO UAEM TIANGUISTENCO"
            c1.font = font_inst
            c1.alignment = align_center
            ws.row_dimensions[1].height = 24

            ws.merge_cells("A2:G2")
            c2 = ws["A2"]
            per_info = f" | Período: {filtro_periodo}" if filtro_periodo and filtro_periodo != "Todos" else ""
            c2.value = f"CÉDULA DE CARGA HORARIA DOCENTE INDIVIDUAL{per_info}"
            c2.font = font_sub
            c2.fill = fill_sub
            c2.alignment = align_center
            ws.row_dimensions[2].height = 22

            ws.merge_cells("A3:G3")
            c3 = ws["A3"]
            c3.value = f"Docente: {pdata['nombre']}   |   No. Cuenta: {pdata['cuenta']}   |   Horas Semanales: {pdata['horas_totales']:.1f} hrs"
            c3.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
            c3.fill = PatternFill(start_color="335522", end_color="335522", fill_type="solid")
            c3.alignment = align_center
            ws.row_dimensions[3].height = 20

            # Encabezados de tabla
            ws.cell(row=4, column=1, value="HORARIO").font = font_hdr
            ws.cell(row=4, column=1).fill = fill_hdr
            ws.cell(row=4, column=1).alignment = align_center
            ws.cell(row=4, column=1).border = border_std
            ws.column_dimensions["A"].width = 16

            for col_i, d in enumerate(dias, start=2):
                col_let = get_column_letter(col_i)
                ws.cell(row=4, column=col_i, value=d.upper()).font = font_hdr
                ws.cell(row=4, column=col_i).fill = fill_hdr
                ws.cell(row=4, column=col_i).alignment = align_center
                ws.cell(row=4, column=col_i).border = border_std
                ws.column_dimensions[col_let].width = 24
            ws.row_dimensions[4].height = 24

            # Filas de datos
            for r_idx, h_str in enumerate(horas, start=5):
                h_num = 7 + (r_idx - 5)
                m_start = h_num * 60
                m_end = (h_num + 1) * 60

                c_h = ws.cell(row=r_idx, column=1, value=h_str)
                c_h.font = Font(name="Calibri", size=10, bold=True, color="2D3748")
                c_h.fill = fill_hora
                c_h.alignment = align_center
                c_h.border = border_std
                ws.row_dimensions[r_idx].height = 42

                for c_idx, d in enumerate(dias, start=2):
                    cell = ws.cell(row=r_idx, column=c_idx)
                    cell.border = border_std
                    coinc = [
                        s for s in pdata["sesiones"]
                        if s["dia"] == d and s["ini_min"] < m_end and s["fin_min"] > m_start
                    ]
                    if coinc:
                        s = coinc[0]
                        cell.value = f"{cls._abreviar_materia(s['materia'])}\nGrupo: {s['grupo']} | Aula: {s['salon']}"
                        cell.font = font_data
                        cell.fill = fill_slot
                        cell.alignment = align_center
                    else:
                        cell.value = ""
                        cell.font = font_empty

            # Firmas
            f_row = 5 + len(horas) + 2
            ws.merge_cells(start_row=f_row, start_column=2, end_row=f_row, end_column=3)
            ws.cell(row=f_row, column=2, value="_________________________________________\nFirma del Docente").alignment = align_center
            ws.cell(row=f_row, column=2).font = font_firma

            ws.merge_cells(start_row=f_row, start_column=5, end_row=f_row, end_column=6)
            ws.cell(row=f_row, column=5, value="_________________________________________\nJefatura de División Académica").alignment = align_center
            ws.cell(row=f_row, column=5).font = font_firma
            ws.row_dimensions[f_row].height = 35

        wb.save(ruta_archivo)
        return {"exito": True, "ruta": ruta_archivo, "total_profesores": len(profesores_dict)}

    @classmethod
    def generar_excel_fichas_grupos(cls, ruta_archivo, filtro_semestre=None, filtro_periodo=None):
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "Sin conexión a base de datos."}
            cur, conn = ctx

            condiciones = ["(a.estado IS NULL OR a.estado != 'cancelada')"]
            params = []
            if filtro_semestre and filtro_semestre != "Todos":
                condiciones.append("g.nivel = %s")
                params.append(filtro_semestre)
            if filtro_periodo and filtro_periodo != "Todos":
                condiciones.append("a.periodo = %s")
                params.append(filtro_periodo)

            cur.execute(f"""
                SELECT 
                    a.grupo_id,
                    IFNULL(g.nivel, '1') AS nivel,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(p.nombre, 'Sin profesor') AS profesor_nombre,
                    IFNULL(h.salon_id, 'Sin aula') AS salon_id,
                    h.dia,
                    h.hora_inicio,
                    h.hora_fin,
                    IFNULL(a.modalidad, 'Presencial') AS modalidad,
                    a.periodo
                FROM asignaciones a
                JOIN horarios h ON a.asignacion_id = h.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                LEFT JOIN grupos g ON a.grupo_id = g.grupo_id
                WHERE {" AND ".join(condiciones)}
                ORDER BY g.nivel, a.grupo_id, h.dia, h.hora_inicio
            """, tuple(params))
            filas = cur.fetchall()

        if not filas:
            return {"exito": False, "mensaje": "No se encontraron horarios de grupos para exportar."}

        grupos_dict = {}
        for r in filas:
            gid = r[0]
            if gid not in grupos_dict:
                grupos_dict[gid] = {
                    "grupo": gid, "nivel": r[1], "sesiones": [], "horas_totales": 0.0
                }
            h_i = cls._formatear_hora(r[7])
            h_f = cls._formatear_hora(r[8])
            ini_min = cls._hora_a_minutos(h_i)
            fin_min = cls._hora_a_minutos(h_f)
            grupos_dict[gid]["horas_totales"] += (fin_min - ini_min) / 60.0
            grupos_dict[gid]["sesiones"].append({
                "materia": r[3], "profesor": r[4], "salon": r[5],
                "dia": cls._normalizar_dia(r[6]),
                "hora_i": h_i, "hora_f": h_f, "ini_min": ini_min, "fin_min": fin_min,
                "modalidad": r[9]
            })

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        font_inst = Font(name="Calibri", size=11, bold=True, color="1A3311")
        font_sub = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_data = Font(name="Calibri", size=9.5, bold=True, color=cls.HEX_VERDE_TEXTO)
        font_empty = Font(name="Calibri", size=9)

        fill_hdr = PatternFill(start_color=cls.HEX_VERDE_UAEMEX, end_color=cls.HEX_VERDE_UAEMEX, fill_type="solid")
        fill_sub = PatternFill(start_color="25401A", end_color="25401A", fill_type="solid")
        fill_slot = PatternFill(start_color=cls.HEX_VERDE_BG_CLARO, end_color=cls.HEX_VERDE_BG_CLARO, fill_type="solid")
        fill_hora = PatternFill(start_color="F8FAF6", end_color="F8FAF6", fill_type="solid")

        thin_side = Side(border_style="thin", color="A3CF9D")
        border_std = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        horas = [f"{h:02d}:00 - {h+1:02d}:00" for h in range(7, 18)]

        for gid, gdata in sorted(grupos_dict.items(), key=lambda x: str(x[0])):
            ws = wb.create_sheet(title=f"Grupo_{gid}")

            ws.merge_cells("A1:G1")
            c1 = ws["A1"]
            c1.value = "UNIVERSIDAD AUTÓNOMA DEL ESTADO DE MÉXICO - CENTRO UNIVERSITARIO UAEM TIANGUISTENCO"
            c1.font = font_inst
            c1.alignment = align_center
            ws.row_dimensions[1].height = 24

            ws.merge_cells("A2:G2")
            c2 = ws["A2"]
            c2.value = f"HORARIO SEMANAL DE CLASES - GRUPO {gid}"
            c2.font = font_sub
            c2.fill = fill_sub
            c2.alignment = align_center
            ws.row_dimensions[2].height = 22

            ws.merge_cells("A3:G3")
            c3 = ws["A3"]
            per_info = f" | Período: {filtro_periodo}" if filtro_periodo and filtro_periodo != "Todos" else ""
            c3.value = f"Grupo: {gid}   |   Semestre: {gdata['nivel']}   |   Horas Semanales: {gdata['horas_totales']:.1f} hrs{per_info}"
            c3.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
            c3.fill = PatternFill(start_color="335522", end_color="335522", fill_type="solid")
            c3.alignment = align_center
            ws.row_dimensions[3].height = 20

            ws.cell(row=4, column=1, value="HORARIO").font = font_hdr
            ws.cell(row=4, column=1).fill = fill_hdr
            ws.cell(row=4, column=1).alignment = align_center
            ws.cell(row=4, column=1).border = border_std
            ws.column_dimensions["A"].width = 16

            for col_i, d in enumerate(dias, start=2):
                col_let = get_column_letter(col_i)
                ws.cell(row=4, column=col_i, value=d.upper()).font = font_hdr
                ws.cell(row=4, column=col_i).fill = fill_hdr
                ws.cell(row=4, column=col_i).alignment = align_center
                ws.cell(row=4, column=col_i).border = border_std
                ws.column_dimensions[col_let].width = 24
            ws.row_dimensions[4].height = 24

            for r_idx, h_str in enumerate(horas, start=5):
                h_num = 7 + (r_idx - 5)
                m_start = h_num * 60
                m_end = (h_num + 1) * 60

                c_h = ws.cell(row=r_idx, column=1, value=h_str)
                c_h.font = Font(name="Calibri", size=10, bold=True, color="2D3748")
                c_h.fill = fill_hora
                c_h.alignment = align_center
                c_h.border = border_std
                ws.row_dimensions[r_idx].height = 42

                for c_idx, d in enumerate(dias, start=2):
                    cell = ws.cell(row=r_idx, column=c_idx)
                    cell.border = border_std
                    coinc = [
                        s for s in gdata["sesiones"]
                        if s["dia"] == d and s["ini_min"] < m_end and s["fin_min"] > m_start
                    ]
                    if coinc:
                        s = coinc[0]
                        cell.value = f"{s['materia']}\nAula: {s['salon']} | Prof: {s['profesor'][:20]}"
                        cell.font = font_data
                        cell.fill = fill_slot
                        cell.alignment = align_center
                    else:
                        cell.value = ""
                        cell.font = font_empty

        wb.save(ruta_archivo)
        return {"exito": True, "ruta": ruta_archivo, "total_grupos": len(grupos_dict)}

    @classmethod
    def generar_excel_cedulas_aulas(cls, ruta_archivo, filtro_periodo=None):
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "Sin conexión a base de datos."}
            cur, conn = ctx

            cur.execute("SELECT salon_id, capacidad, IFNULL(tipo, 'Normal') FROM salones ORDER BY salon_id")
            salones_db = cur.fetchall()

            condiciones = ["(a.estado IS NULL OR a.estado != 'cancelada')"]
            params = []
            if filtro_periodo and filtro_periodo != "Todos":
                condiciones.append("a.periodo = %s")
                params.append(filtro_periodo)

            cur.execute(f"""
                SELECT 
                    h.salon_id,
                    a.grupo_id,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(p.nombre, 'Sin profesor') AS profesor_nombre,
                    h.dia,
                    h.hora_inicio,
                    h.hora_fin,
                    IFNULL(a.modalidad, 'Presencial') AS modalidad,
                    a.periodo
                FROM horarios h
                JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                WHERE {" AND ".join(condiciones)}
                ORDER BY h.salon_id, h.dia, h.hora_inicio
            """, tuple(params))
            filas_horarios = cur.fetchall()

        if not salones_db and not filas_horarios:
            return {"exito": False, "mensaje": "No se encontraron salones ni ocupación para exportar."}

        aulas_dict = {}
        for srow in salones_db:
            sid = srow[0]
            aulas_dict[sid] = {
                "id": sid, "capacidad": srow[1], "tipo": srow[2],
                "sesiones": [], "horas_ocupadas": 0.0
            }

        for r in filas_horarios:
            sid = r[0]
            if not sid or sid == "Sin aula":
                continue
            if sid not in aulas_dict:
                aulas_dict[sid] = {
                    "id": sid, "capacidad": 30, "tipo": "Normal", "sesiones": [], "horas_ocupadas": 0.0
                }
            h_i = cls._formatear_hora(r[6])
            h_f = cls._formatear_hora(r[7])
            ini_min = cls._hora_a_minutos(h_i)
            fin_min = cls._hora_a_minutos(h_f)
            aulas_dict[sid]["horas_ocupadas"] += (fin_min - ini_min) / 60.0
            aulas_dict[sid]["sesiones"].append({
                "grupo": r[1], "materia": r[3], "profesor": r[4],
                "dia": cls._normalizar_dia(r[5]),
                "hora_i": h_i, "hora_f": h_f, "ini_min": ini_min, "fin_min": fin_min,
                "modalidad": r[8]
            })

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        font_inst = Font(name="Calibri", size=11, bold=True, color="1A3311")
        font_sub = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        font_hdr = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_data = Font(name="Calibri", size=9.5, bold=True, color=cls.HEX_VERDE_TEXTO)
        font_empty = Font(name="Calibri", size=9)

        fill_hdr = PatternFill(start_color=cls.HEX_VERDE_UAEMEX, end_color=cls.HEX_VERDE_UAEMEX, fill_type="solid")
        fill_sub = PatternFill(start_color="25401A", end_color="25401A", fill_type="solid")
        fill_slot = PatternFill(start_color=cls.HEX_VERDE_BG_CLARO, end_color=cls.HEX_VERDE_BG_CLARO, fill_type="solid")
        fill_hora = PatternFill(start_color="F8FAF6", end_color="F8FAF6", fill_type="solid")

        thin_side = Side(border_style="thin", color="A3CF9D")
        border_std = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        horas = [f"{h:02d}:00 - {h+1:02d}:00" for h in range(7, 18)]

        for sid, sdata in sorted(aulas_dict.items(), key=lambda x: str(x[0])):
            ws = wb.create_sheet(title=f"Aula_{sid}")

            ws.merge_cells("A1:G1")
            c1 = ws["A1"]
            c1.value = "UNIVERSIDAD AUTÓNOMA DEL ESTADO DE MÉXICO - CENTRO UNIVERSITARIO UAEM TIANGUISTENCO"
            c1.font = font_inst
            c1.alignment = align_center
            ws.row_dimensions[1].height = 24

            ws.merge_cells("A2:G2")
            c2 = ws["A2"]
            c2.value = f"CÉDULA DE OCUPACIÓN SEMANAL - AULA: {sid}"
            c2.font = font_sub
            c2.fill = fill_sub
            c2.alignment = align_center
            ws.row_dimensions[2].height = 22

            ws.merge_cells("A3:G3")
            c3 = ws["A3"]
            per_info = f" | Período: {filtro_periodo}" if filtro_periodo and filtro_periodo != "Todos" else ""
            c3.value = f"Salón: {sid}   |   Capacidad: {sdata['capacidad']}   |   Tipo: {sdata['tipo']}   |   Ocupación: {sdata['horas_ocupadas']:.1f} hrs/sem{per_info}"
            c3.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
            c3.fill = PatternFill(start_color="335522", end_color="335522", fill_type="solid")
            c3.alignment = align_center
            ws.row_dimensions[3].height = 20

            ws.cell(row=4, column=1, value="HORARIO").font = font_hdr
            ws.cell(row=4, column=1).fill = fill_hdr
            ws.cell(row=4, column=1).alignment = align_center
            ws.cell(row=4, column=1).border = border_std
            ws.column_dimensions["A"].width = 16

            for col_i, d in enumerate(dias, start=2):
                col_let = get_column_letter(col_i)
                ws.cell(row=4, column=col_i, value=d.upper()).font = font_hdr
                ws.cell(row=4, column=col_i).fill = fill_hdr
                ws.cell(row=4, column=col_i).alignment = align_center
                ws.cell(row=4, column=col_i).border = border_std
                ws.column_dimensions[col_let].width = 24
            ws.row_dimensions[4].height = 24

            for r_idx, h_str in enumerate(horas, start=5):
                h_num = 7 + (r_idx - 5)
                m_start = h_num * 60
                m_end = (h_num + 1) * 60

                c_h = ws.cell(row=r_idx, column=1, value=h_str)
                c_h.font = Font(name="Calibri", size=10, bold=True, color="2D3748")
                c_h.fill = fill_hora
                c_h.alignment = align_center
                c_h.border = border_std
                ws.row_dimensions[r_idx].height = 42

                for c_idx, d in enumerate(dias, start=2):
                    cell = ws.cell(row=r_idx, column=c_idx)
                    cell.border = border_std
                    coinc = [
                        s for s in sdata["sesiones"]
                        if s["dia"] == d and s["ini_min"] < m_end and s["fin_min"] > m_start
                    ]
                    if coinc:
                        s = coinc[0]
                        cell.value = f"Gpo: {s['grupo']} | {s['materia'][:20]}\nProf: {s['profesor'][:20]}"
                        cell.font = font_data
                        cell.fill = fill_slot
                        cell.alignment = align_center
                    else:
                        cell.value = ""
                        cell.font = font_empty

        wb.save(ruta_archivo)
        return {"exito": True, "ruta": ruta_archivo, "total_aulas": len(aulas_dict)}
