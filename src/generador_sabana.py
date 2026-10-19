# -*- coding: utf-8 -*-
"""
Módulo de Generación de Sábana Matricial Consolidada de Horarios (SAGA 2.0)
Genera reportes ejecutivos en Excel y PDF donde se presentan todos los grupos
de un mismo semestre lado a lado para verificar la compatibilidad y distribución general.
"""

import datetime
import os
import sqlite3
import unicodedata
from src.conexion import obtener_cursor

class GeneradorSabana:
    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    HORAS = [f"{h:02d}:00" for h in range(7, 18)]

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
        """
        Retorna los horarios organizados por:
        datos[semestre_id]['grupos'][grupo_id] = list of sesiones
        """
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
                    IFNULL(a.modalidad, 'Presencial') AS modalidad,
                    a.periodo
                FROM asignaciones a
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                LEFT JOIN horarios h ON a.asignacion_id = h.asignacion_id
                LEFT JOIN grupos g ON a.grupo_id = g.grupo_id
                WHERE (a.estado IS NULL OR a.estado != 'cancelada')
                  AND h.dia IS NOT NULL
                ORDER BY g.nivel, a.grupo_id, h.dia, h.hora_inicio
            """)
            filas = cur.fetchall()

        resultado = {}
        for f in filas:
            sem_id, g_id, asig_id, m_id, m_nom, prof_nom, salon_id, dia, hi, hf, modalidad, periodo = f
            sem_str = str(sem_id).strip()
            if filtro_semestre and filtro_semestre != "Todos" and sem_str != str(filtro_semestre).strip():
                continue
            if filtro_periodo and periodo and str(periodo).upper() != str(filtro_periodo).upper():
                continue

            if sem_str not in resultado:
                resultado[sem_str] = {
                    "nombre": f"Semestre {sem_str}",
                    "grupos": {}
                }

            if g_id not in resultado[sem_str]["grupos"]:
                resultado[sem_str]["grupos"][g_id] = []

            hi_str = cls._formatear_hora(hi)
            hf_str = cls._formatear_hora(hf)
            dia_norm = cls._normalizar_dia(dia)

            resultado[sem_str]["grupos"][g_id].append({
                "asignacion_id": asig_id,
                "materia_id": m_id,
                "materia_nombre": m_nom,
                "profesor_nombre": prof_nom,
                "salon_id": salon_id,
                "dia": dia_norm,
                "hora_inicio": hi_str,
                "hora_fin": hf_str,
                "ini_min": cls._hora_a_minutos(hi_str),
                "fin_min": cls._hora_a_minutos(hf_str),
                "modalidad": modalidad,
                "periodo": periodo
            })

        return resultado

    @classmethod
    def generar_excel_sabana(cls, ruta_archivo, filtro_semestre=None, filtro_periodo=None):
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        datos = cls.obtener_datos(filtro_semestre, filtro_periodo)
        if not datos:
            return {"exito": False, "mensaje": "No se encontraron asignaciones para los filtros seleccionados."}

        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # Quitar hoja default vacía

        # Estilos base
        font_titulo = Font(name="Calibri", size=15, bold=True, color="FFFFFF")
        font_sub = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_hdr_grupo = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_dia = Font(name="Calibri", size=10, bold=True, color="1F2937")
        font_hora = Font(name="Calibri", size=9, bold=True, color="374151")
        font_celda = Font(name="Calibri", size=8, color="111827")
        font_celda_neg = Font(name="Calibri", size=8, bold=True, color="111827")

        fill_titulo = PatternFill(start_color="0A0F1E", end_color="0A0F1E", fill_type="solid")
        fill_sub = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        fill_dia = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        fill_hora = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        colores_grupos = ["2563EB", "0D9488", "7C3AED", "D97706", "DC2626", "059669", "4F46E5", "B45309"]

        thin_side = Side(border_style="thin", color="CBD5E1")
        border_box = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

        total_grupos_exportados = 0

        # Generar una pestaña por cada Semestre
        for sem_id, sem_data in sorted(datos.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 99):
            grupos_dict = sem_data["grupos"]
            lista_grupos = sorted(grupos_dict.keys())
            if not lista_grupos:
                continue

            total_grupos_exportados += len(lista_grupos)
            nombre_hoja = f"Semestre {sem_id}"[:31]
            ws = wb.create_sheet(title=nombre_hoja)
            ws.views.sheetView[0].showGridLines = True

            # Fila 1: Título Principal
            periodo_txt = f" - Periodo {filtro_periodo}" if filtro_periodo else ""
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=2 + len(lista_grupos))
            c_tit = ws.cell(row=1, column=1, value=f"SÁBANA MATRICIAL CONSOLIDADA - SEMESTRE {sem_id}{periodo_txt}")
            c_tit.font = font_titulo
            c_tit.fill = fill_titulo
            c_tit.alignment = align_center
            ws.row_dimensions[1].height = 34

            # Fila 2: Subtítulo de Información
            ahora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2 + len(lista_grupos))
            c_sub = ws.cell(row=2, column=1, value=f"Fecha de Emisión: {ahora}   |   Total de Grupos: {len(lista_grupos)}   |   SAGA 2.0")
            c_sub.font = font_sub
            c_sub.fill = fill_sub
            c_sub.alignment = align_center
            ws.row_dimensions[2].height = 22

            # Fila 3: Encabezados de Columnas (Día, Horario, Grupo 1, Grupo 2...)
            ws.cell(row=3, column=1, value="DÍA").font = font_sub
            ws.cell(row=3, column=1).fill = fill_sub
            ws.cell(row=3, column=1).alignment = align_center
            ws.cell(row=3, column=1).border = border_box

            ws.cell(row=3, column=2, value="HORARIO").font = font_sub
            ws.cell(row=3, column=2).fill = fill_sub
            ws.cell(row=3, column=2).alignment = align_center
            ws.cell(row=3, column=2).border = border_box

            for col_idx, g_id in enumerate(lista_grupos, start=3):
                col_hex = colores_grupos[(col_idx - 3) % len(colores_grupos)]
                fill_g = PatternFill(start_color=col_hex, end_color=col_hex, fill_type="solid")
                c_g = ws.cell(row=3, column=col_idx, value=f"GRUPO {g_id}")
                c_g.font = font_hdr_grupo
                c_g.fill = fill_g
                c_g.alignment = align_center
                c_g.border = border_box

            ws.row_dimensions[3].height = 26

            # Llenado de Filas: Día por Día, Franja por Franja (de 07:00 a 17:00)
            franjas = [
                ("07:00", "08:00"), ("08:00", "09:00"), ("09:00", "10:00"),
                ("10:00", "11:00"), ("11:00", "12:00"), ("12:00", "13:00"),
                ("13:00", "14:00"), ("14:00", "15:00"), ("15:00", "16:00"),
                ("16:00", "17:00")
            ]

            fila_actual = 4
            for dia in cls.DIAS:
                fila_inicio_dia = fila_actual
                for h_ini_f, h_fin_f in franjas:
                    f_ini_min = cls._hora_a_minutos(h_ini_f)
                    f_fin_min = cls._hora_a_minutos(h_fin_f)

                    # Columna B: Franja Horaria
                    c_h = ws.cell(row=fila_actual, column=2, value=f"{h_ini_f} - {h_fin_f}")
                    c_h.font = font_hora
                    c_h.fill = fill_hora
                    c_h.alignment = align_center
                    c_h.border = border_box

                    # Columnas C..N: Grupos
                    for col_idx, g_id in enumerate(lista_grupos, start=3):
                        sesiones_grupo = grupos_dict.get(g_id, [])
                        coincidentes = [
                            s for s in sesiones_grupo
                            if s['dia'] == dia and s['ini_min'] < f_fin_min and s['fin_min'] > f_ini_min
                        ]

                        c_val = ws.cell(row=fila_actual, column=col_idx)
                        c_val.border = border_box
                        c_val.alignment = align_center

                        if coincidentes:
                            # Formatear el contenido de la materia en este bloque
                            partes_txt = []
                            for ses in coincidentes:
                                modal_txt = " [MT]" if ses.get('modalidad') == 'Mediación Tecnológica' else ""
                                partes_txt.append(
                                    f"{ses['materia_nombre']}\n"
                                    f"Prof: {ses['profesor_nombre']}\n"
                                    f"Aula: {ses['salon_id']}{modal_txt}"
                                )
                            c_val.value = "\n---\n".join(partes_txt)
                            c_val.font = font_celda
                            # Color suave si tiene clase
                            c_val.fill = PatternFill(start_color="EFF6FF", end_color="EFF6FF", fill_type="solid")
                        else:
                            c_val.value = ""
                            c_val.font = font_celda

                    ws.row_dimensions[fila_actual].height = 42
                    fila_actual += 1

                # Combinar celdas de la columna Día verticalmente para toda la jornada
                ws.merge_cells(start_row=fila_inicio_dia, start_column=1, end_row=fila_actual - 1, end_column=1)
                c_dia = ws.cell(row=fila_inicio_dia, column=1, value=dia.upper())
                c_dia.font = font_dia
                c_dia.fill = fill_dia
                c_dia.alignment = align_center
                c_dia.border = border_box

            # Autoajustar anchos de columna
            ws.column_dimensions['A'].width = 13
            ws.column_dimensions['B'].width = 15
            for col_idx in range(3, 3 + len(lista_grupos)):
                col_letter = get_column_letter(col_idx)
                ws.column_dimensions[col_letter].width = 28

        wb.save(ruta_archivo)
        return {
            "exito": True,
            "ruta": ruta_archivo,
            "total_semestres": len(datos),
            "total_grupos": total_grupos_exportados
        }

    @classmethod
    def generar_pdf_sabana(cls, ruta_archivo, filtro_semestre=None, filtro_periodo=None):
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages

        datos = cls.obtener_datos(filtro_semestre, filtro_periodo)
        if not datos:
            return {"exito": False, "mensaje": "No se encontraron asignaciones para los filtros seleccionados."}

        franjas = [
            ("07:00", "08:00"), ("08:00", "09:00"), ("09:00", "10:00"),
            ("10:00", "11:00"), ("11:00", "12:00"), ("12:00", "13:00"),
            ("13:00", "14:00"), ("14:00", "15:00"), ("15:00", "16:00"),
            ("16:00", "17:00")
        ]

        with PdfPages(ruta_archivo) as pdf:
            for sem_id, sem_data in sorted(datos.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 99):
                grupos_dict = sem_data["grupos"]
                lista_grupos = sorted(grupos_dict.keys())
                if not lista_grupos:
                    continue

                # Dividir días en páginas para que la tabla sea perfectamente legible
                # 2 días por página o 1 día por página según cantidad de grupos
                dias_por_pagina = 1 if len(lista_grupos) > 4 else 2
                chunk_dias = [cls.DIAS[i:i + dias_por_pagina] for i in range(0, len(cls.DIAS), dias_por_pagina)]

                for lote_dias in chunk_dias:
                    # Configurar figura horizontal landscape
                    fig, ax = plt.subplots(figsize=(15, 9.5))
                    ax.axis('tight')
                    ax.axis('off')

                    columnas = ['Día', 'Horario'] + [f"Gpo {g}" for g in lista_grupos]
                    filas_tabla = []

                    for dia in lote_dias:
                        for h_ini_f, h_fin_f in franjas:
                            f_ini_min = cls._hora_a_minutos(h_ini_f)
                            f_fin_min = cls._hora_a_minutos(h_fin_f)
                            fila = [dia, f"{h_ini_f}-{h_fin_f}"]

                            for g_id in lista_grupos:
                                sesiones_grupo = grupos_dict.get(g_id, [])
                                coincidentes = [
                                    s for s in sesiones_grupo
                                    if s['dia'] == dia and s['ini_min'] < f_fin_min and s['fin_min'] > f_ini_min
                                ]
                                if coincidentes:
                                    s = coincidentes[0]
                                    txt = f"{s['materia_nombre'][:22]}\n{s['profesor_nombre'][:20]}\nAula: {s['salon_id']}"
                                    fila.append(txt)
                                else:
                                    fila.append("-")
                            filas_tabla.append(fila)

                    # Crear tabla en matplotlib
                    dias_tit = " y ".join(lote_dias)
                    periodo_txt = f" (Periodo {filtro_periodo})" if filtro_periodo else ""
                    ax.set_title(
                        f"SÁBANA MATRICIAL CONSOLIDADA - SEMESTRE {sem_id}{periodo_txt} - {dias_tit}\n",
                        fontsize=13, fontweight='bold', pad=12
                    )

                    tab = ax.table(
                        cellText=filas_tabla,
                        colLabels=columnas,
                        loc='center',
                        cellLoc='center'
                    )
                    tab.auto_set_font_size(False)
                    tab.set_fontsize(7.5)
                    tab.scale(1.0, 1.8)

                    # Estilar encabezados
                    for col_i in range(len(columnas)):
                        cell = tab[(0, col_i)]
                        cell.set_facecolor('#1E293B')
                        cell.set_text_props(color='white', weight='bold')

                    # Colorear celdas con clase
                    for r_i, r_data in enumerate(filas_tabla, start=1):
                        for c_i in range(2, len(columnas)):
                            cell = tab[(r_i, c_i)]
                            val_txt = r_data[c_i]
                            if val_txt != "-":
                                cell.set_facecolor('#EFF6FF')
                            else:
                                cell.set_facecolor('#FFFFFF')

                    pdf.savefig(fig, bbox_inches='tight', dpi=150)
                    plt.close(fig)

        return {
            "exito": True,
            "ruta": ruta_archivo,
            "total_semestres": len(datos)
        }
