# PLASEM - Control de Personal / Organizador de Horarios y Salones

## 1. DESCRIPCIÓN GENERAL

Sistema de gestión académica que permite administrar profesores, materias, salones y
generar horarios automáticos. Construido con **Python + Tkinter** como interfaz
gráfica y **MySQL** como base de datos.

---

## 2. CÓMO EJECUTAR EL PROGRAMA

```bash
# Desde la raíz del proyecto
python arrancar.py
```

**Requisitos:**

- Python 3.10+
- mysql-connector-python
- Pillow (PIL)
- matplotlib
- numpy
- pandas + openpyxl (para exportar a Excel)

**Instalación de dependencias:**

```bash
pip install mysql-connector-python Pillow matplotlib numpy pandas openpyxl
```

---

## 3. CONEXIÓN A BASE DE DATOS

Archivo: `src/conexion.py`

```python
host = "localhost"
user = "root"
password = "123456"
database = "bd_seso"
port = "3306"
```

**Base de datos:** MySQL llamada `bd_seso`.

---

## 4. ESTRUCTURA DEL PROYECTO

```
servicio_S/
├── arrancar.py                      # Punto de entrada
├── arrancar.spec                    # Configuración PyInstaller
├── DOCUMENTACION.md                 # Este archivo
├── migrar_disponibilidad.sql               # Migración de disponibilidad multi-periodo
├── migrar_grupos.sql                       # Migración: columna nivel en grupos + modalidad en asignaciones
├── migrar_profesores.sql                   # Migración: columna no_cuenta, regenerar profesor_id
├── migrar_asignaciones_periodo.sql         # Migración: columnas periodo, hora_inicio, hora_fin, modalidad
├── migrar_modalidad_periodo.sql            # Migración: columna modalidad en profesor_disponibilidad
├── migrar_salones_mediacion.sql            # Migración: renombrar EN_LINEA → MEDIACION_TECNOLOGICA
├── assets/
│   └── fondo.png                    # Imagen de fondo de la ventana
├── src/
│   ├── conexion.py                  # Conexión a MySQL
│   ├── motor_horarios.py            # Algoritmo original de generación automática
│   ├── motor_horarios_backup.py     # Backup exacto del motor original
│   ├── motor_horarios_nuevo.py      # Motor actual: asigna salones con distr. por horas_semana
│   ├── resp_motor.py                # (vacio - reservado)
│   ├── clases/
│   │   ├── __init__.py
│   │   ├── grupo.py                 # Modelo de grupos (grupo_id, nivel)
│   │   ├── materia.py               # Modelo y guardado de materias
│   │   ├── profesor.py              # Modelo y guardado de profesores
│   │   ├── salon.py                 # Modelo y guardado de salones
│   │   ├── Validar_materia.py       # Validación y registro en BD de materias
│   │   ├── validacion_bd.py         # Validación y registro en BD de profesores
│   │   └── memoria_Horario_Grafico.py # Memoria/ tensor para visualización de horarios
│   └── UI/
│       ├── __init__.py
│       ├── ventana_principal.py     # Ventana principal (pestaña Personal)
│       └── ventana_gestion.py       # Ventana de gestión (pestañas Gestionar, Alertas y Ver Horarios)
```

---

## 5. ARQUITECTURA

### 5.1 Flujo general

```
arrancar.py
    │
    ├── Crea VentanaPrincipal (tk.Tk)
    │       ├── Pestaña "Personal"   (tab_personal)
    │       │       ├── Panel izquierdo: formularios de Profesores, Materias, Salones, Grupos
    │       │       └── Panel derecho: tablas de datos con búsqueda y filtro por semestre
    │       └── Pestaña "Gestión"    (tab_gestion)
    │               └── VentanaGestion (embebida via parent_frame)
    │                       ├── Pestaña "Gestionar": asignaciones manuales y automáticas
    │                       ├── Pestaña "Alertas": detalle de conflictos de asignación
    │                       └── Pestaña "Ver Horarios": visualización gráfica (matplotlib)
    │
    └── mainloop()
```

### 5.2 Base de datos (bd_seso)

**Tablas principales:**

| Tabla                    | Propósito                                      |
|--------------------------|-------------------------------------------------|
| `profesores`             | Profesores (con no_cuenta, profesor_id auto-generado P0001…) |
| `profesor_disponibilidad`| Disponibilidad horaria por día (multi-periodo, con modalidad)|
| `materias`               | Materias con horas, semestre y tipo                         |
| `salones`                | Salones con capacidad y tipo (incluye MEDIACION_TECNOLOGICA)|
| `grupos`                 | Grupos (S1A, S2B, etc.) con nivel (semestre)               |
| `asignaciones`           | Relación profesor-materia-grupo-periodo-modalidad (con estado, hora_inicio, hora_fin)|
| `horarios`               | Horarios generados (salón, día, hora)           |
| `semestres`              | Catálogo de semestres                           |

---

## 6. DESCRIPCIÓN DETALLADA DE CADA ARCHIVO

### 6.1 `arrancar.py` — Punto de entrada

```python
root = tk.Tk()
icono = tk.PhotoImage(file=ruta_recurso('src/UI/logo ph.png'))
root.iconphoto(True, icono)
app = VentanaPrincipal(root)
app.mostrar_datos_profesor()
app.mostrar_datos_materias()
app.mostrar_datos_salones()
app.mostrar_datos_grupos()    # ← Se agregó carga de grupos
root.mainloop()
```

---

### 6.2 `src/conexion.py` — Conexión a BD

Tres funciones:

| Función               | Descripción                                         |
|-----------------------|-----------------------------------------------------|
| `get_conexion()`      | Retorna una conexión mysql.connector o None si falla|
| `obtener_cursor()`    | Context manager que da un cursor normal con commit  |
| `obtener_cursor_dict()`| Ídem pero con cursor dictionary=True                |

`obtener_cursor` se usa con `with` para manejar commit/rollback automático:

```python
with obtener_cursor() as ctx:
    if ctx is None:
        return
    cur, conn = ctx
    cur.execute("SELECT ...")
```

---

### 6.3 `src/clases/profesor.py` — Modelo Profesor

```python
class profesor:
    def __init__(self, cuenta, nombre_completo, periodos):
        # Delega en validar_y_registrar_profesor()
```

- `cuenta`: No. de cuenta proporcionado por el usuario (el `profesor_id` se auto-genera como P0001…)
- `nombre_completo`: Nombre completo (los títulos DR., MTRO., etc. se separan automáticamente)
- `periodos`: Lista de dicts con `{dias, hora_inicio, hora_fin}`

---

### 6.4 `src/clases/validacion_bd.py` — Validación y guardado de profesores

**Funciones:**

| Función                                | Propósito                                    |
|----------------------------------------|----------------------------------------------|
| `formatear_hora(hora_str)`             | Normaliza "7:00" → "07:00:00"               |
| `_generar_profesor_id(cursor)`         | Genera el siguiente ID (P0001, P0002...)     |
| `validar_y_registrar_profesor(...)`     | Inserta o actualiza profesor + disponibilidad|

**Lógica de `validar_y_registrar_profesor`:**

1. Recibe `no_cuenta` (ya no `profesor_id`) y datos del profesor
2. Busca en BD por `no_cuenta` en lugar de `profesor_id`
3. Si existe → actualiza nombre (`nom_profesor`) y re-inserta `profesor_disponibilidad`
4. Si no existe → genera `profesor_id` autocontador (`P0001`, `P0002`...) con `_generar_profesor_id()`, e inserta en `profesores` y `profesor_disponibilidad`
5. Usa `obtener_cursor()` (context manager de `conexion.py`) en lugar de `conexion.connect()`/`cursor.close()` manual
6. Guarda los periodos expandiendo cada día como fila individual en `profesor_disponibilidad` (con `hora_inicio`, `hora_fin`, `dia`)

---

### 6.5 `src/clases/materia.py` — Modelo Materia

```python
class materia:
    def __init__(self, clave, nombre, horas_semana, semestre, tipo):
```

- `tipo`: "Normal", "Tecnológica", "Laboratorio" o "Auditorio"

Delega en `Validar_materia.validar_y_registrar_materia()`.

---

### 6.6 `src/clases/Validar_materia.py` — Validación y guardado de materias

**Función principal:** `validar_y_registrar_materia(clave, nombre, horas_semana, semestre, tipo)`

1. Verifica si la materia ya existe por `materia_id`
2. Si existe → pregunta si desea actualizar (incluyendo el tipo)
3. Si no existe → inserta con `tipo` ("Normal", "Tecnológica", "Laboratorio", "Auditorio")

---

### 6.7 `src/clases/salon.py` — Modelo Salón

```python
class salon:
    def __init__(self, numero_aula, capacidad, tipo):
```

Valida que capacidad sea numérico, luego inserta en tabla `salones` usando `obtener_cursor()`.
Los salones con tipo `MEDIACION_TECNOLOGICA` se filtran automáticamente al mostrar la tabla de salones en la UI.

---

### 6.8 `src/clases/grupo.py` — Modelo Grupo

```python
class grupo:
    def __init__(self, grupo_id, nivel):
```

- `grupo_id`: identificador del grupo (ej. "101", "101I")
- `nivel`: semestre al que pertenece (1-9)
- Inserta o actualiza en tabla `grupos` usando `obtener_cursor()`

---

### 6.9 `src/motor_horarios_nuevo.py` — ASIGNACIÓN DE SALONES

**Clase principal:** `GeneradorHorarios`

**Nota:** Este es el motor activo que reemplazó al original (`motor_horarios.py`).
El usuario define los horarios (días y horas) al crear asignaciones con periodo fijo
(`hora_inicio`, `hora_fin`). El motor asigna **salones** y **distribuye las
sesiones** según `horas_semana` de la materia.

#### 6.9.1 Concepto de SLOT

El día se divide en **30 slots** de 30 minutos cada uno, empezando a las 7:00 AM:

```
Slot  0 = 07:00
Slot  1 = 07:30
Slot  2 = 08:00
...
Slot 29 = 21:30
```

Conversiones: `_hora_a_slot()` y `_slot_a_hora()`.

#### 6.9.2 Normalización de días

Los días en `profesor_disponibilidad` se almacenan como números (`"0"` = Lunes,
`"1"` = Martes… `"5"` = Sábado). En `cargar_datos()`, `_normalizar_dia()` los
convierte a nombres en español para usarlos consistentemente en los horarios.

```python
MAPA_NUM_A_DIA = {"0": "Lunes", "1": "Martes", …, "5": "Sábado", "6": "Domingo"}
```

#### 6.9.3 Matrices de ocupación

Tres diccionarios booleanos que registran ocupación slot por slot:

| Diccionario                    | Clave                          | Propósito               |
|-------------------------------|--------------------------------|-------------------------|
| `ocupacion_salones[dia,salon,slot]` | (str, str, int) → bool  | Salón ocupado?          |
| `ocupacion_profesores[dia,prof,slot]`| (str, str, int) → bool  | Profesor ocupado?       |
| `ocupacion_grupos[dia,grupo,slot]`  | (str, str, int) → bool  | Grupo ocupado?          |

#### 6.9.4 Auto-creación de salones de mediación

En `cargar_datos()`, el motor cuenta cuántas asignaciones tienen modalidad
"Mediacion Tecnologica" y auto-crea salones `MEDIACION_TECNOLOGICA_N` si los
existentes no son suficientes.

#### 6.9.5 Flujo de `ejecutar(modo)`

```
ejecutar(modo)
  ├── cargar_datos(modo)         → Carga asignaciones (con hora_i/hora_f,
  │                                horas_semana de materia),
  │                                disponibilidad por profesor (días normalizados),
  │                                salones (auto-crea MT si faltan)
  ├── _limpiar_matrices()        → Resetea ocupación + uso_salones +
  │                                salon_por_materia_profesor (caché de salón preferido)
  ├── [si modo=parcial] _cargar_horarios_existentes() → Marca horarios previos
  ├── Ordenar asignaciones:
  │      1. Presenciales primero, mediación tecnológica después
  │      2. Por semestre (menor primero)
  │      3. Tecnológicas/Laboratorio primero, Normal después
  │      4. Más horas primero
  │
  └── Para cada asignación:
       ├── horas_totales = horas_semana de la materia
       ├── slot_inicio / slot_duracion desde hora_inicio / hora_fin
       │
       ├── _dias_disponibles_para_horario(asignacion)
       │   → Filtra profesor_disponibilidad buscando días donde
       │     [hora_inicio, hora_fin] quepa dentro del rango del profesor
       │
       ├── _salones_compatibles(tipo_materia, es_mediacion)
       │
       ├── _asignar_dias_a_salon(asignacion, dias, salon)
       │   │
       │   │  total_bloques = horas_semana × 2     (bloques de 30 min por semana)
       │   │  session_blocks = slot_duracion        (ventana hora_inicio→hora_fin)
       │   │  sessions_needed = total_bloques / session_blocks
       │   │
       │   │  Si sessions_needed < 1:
       │   │    → La ventana es más grande de lo necesario
       │   │    → session_blocks = max(ceil(total_bloques / num_dias), 4)
       │   │    → Así cada sesión dura ~2h y se reparten entre los días
       │   │
       │   │  Por cada día disponible (y si caben varias, apiladas):
       │   │    mientras quepan sesiones en la ventana:
       │   │      crear horario en ese día
       │   │      avanzar slot_inicio + session_blocks
       │   │
       │   └── Devuelve cantidad de bloques asignados (>0 = éxito)
       │
       ├── [SALÓN PREFERIDO (optimización)]:
       │   Si el par (profesor_id, materia_id) ya tiene un salón asignado
       │   de otro grupo, intentar usar ESE MISMO SALÓN primero
       │   (caché: salon_por_materia_profesor)
       │
       ├── [FALLBACK]:
       │   Si el salón preferido no sirve, probar cada salón compatible
       │   por orden de uso (menos usado primero)
       │
       └── [Si falló todo]:
           → Registrar en el caché el primer salón que funcionó
           → [Si falló en todos] Generar alerta con diagnóstico

  guardar_en_bd() → Inserta horarios y marca asignaciones como 'asignado'
```

#### 6.9.6 Optimización: mismo salón para misma materia-profesor

El diccionario `salon_por_materia_profesor[(profesor_id, materia_id)] = salon_id`
se usa para que **un maestro que da la misma materia en varios grupos distintos
reciba el mismo salón para todas**, evitando que tenga que moverse por la
universidad entre clases.

1. Cuando se asigna exitosamente un salón, se guarda en el caché
2. Para la siguiente asignación del mismo par (profesor, materia), se intenta
   ese salón primero
3. Si está ocupado en alguno de los días/horarios, se prueba con otros salones
   y el caché se actualiza

#### 6.9.7 Cálculo de sesiones

El motor determina automáticamente cuántas sesiones semanales crear:

| Dato                          | Origen                    | Ejemplo               |
|-------------------------------|---------------------------|-----------------------|
| `horas_semana`                | Tabla `materias`          | 4 h/semana            |
| `slot_duracion`               | `hora_fin − hora_inicio`  | 6h (ventana 7–13)     |
| `total_bloques`               | `horas_semana × 2`        | 8 bloques             |
| `num_dias`                    | Disponibilidad profesor   | 2 días (Lun, Mié)     |
| `session_blocks` (final)      | `total_bloques / num_dias`| 4 bloques = 2h        |

Si `session_blocks` inicial (la ventana) da menos de 1 sesión, se recalcula
distribuyendo `total_bloques / num_dias`, con un mínimo de 4 bloques (2h).

#### 6.9.8 Diagnóstico de fallos

Cuando una asignación no se puede realizar, se genera una alerta con:
- Causas identificadas (falta de salones compatibles, disponibilidad insuficiente)
- Sugerencias de solución
- Detalle de días disponibles y salones compatibles con espacio libre

---

### 6.10 `src/clases/memoria_Horario_Grafico.py` — Tensor de horarios para visualización

**Clase:** `MemoriaHorarioGrafico` (singleton via instancia global)

**Estructura del tensor:**

```python
tensor_actual[entidad_idx, slot, dia] = "texto_celda"
```

Donde:
- `entidad_idx`: índice del salón, profesor o grupo
- `slot`: 0-29 (media hora cada uno)
- `dia`: 0=hora, 1=Lunes, ... 6=Sábado (columna 7 adicional para datos nulos)

**Columnas del tensor:**

| Columna | Contenido          |
|---------|--------------------|
| 0       | Etiqueta horaria   |
| 1-6     | Lunes a Sábado     |

**Texto de celda por modo:**

| Modo      | Formato de celda                  |
|-----------|-----------------------------------|
| Salón     | `Materia\nProfesor\nGrupo`        |
| Profesor  | `Materia\nSalón: X\nGrupo: Y`     |
| Grupo     | `Materia\nProfesor\nSalón: X`     |

**Cambios no documentados:**

- Los grupos se cargan dinámicamente desde BD mediante `_cargar_grupos_desde_bd()` (ya no hay diccionario fijo).
- **Modo Auditorio**: si la materia tiene tipo `Auditorio`, el horario asignado a un grupo se replica visualmente a todos los grupos del mismo semestre en el tensor.

---

### 6.11 `src/UI/ventana_principal.py` — Interfaz de Personal

**Clase:** `VentanaPrincipal`

#### Pestaña Personal (tab_personal)

Panel izquierdo (con scroll):
- **Sección Profesores**: campos No. Cuenta, Nombre(s), Apellidos, periodos de disponibilidad, botones Guardar/Eliminar/Limpiar
- **Sección Materias**: campos Clave, Nombre, Horas Semana, Semestre, Prioridad/Preferencia (Normal, Tecnológica, Laboratorio, Auditorio), botones Agregar/Eliminar
- **Sección Salones**: campos Número de aula, Capacidad, Tipo (Normal, Tecnológica, Laboratorio, Auditorio), botones Agregar/Eliminar
- **Sección Grupos**: campos Grupo (ID), Semestre (nivel), botones Agregar/Eliminar

Panel derecho:
- Tabla de profesores registrados con búsqueda por texto
- Tabla de materias registradas con búsqueda y filtro por semestre
- Tabla de salones registrados (filtra automáticamente salones MEDIACION_TECNOLOGICA)
- Tabla de grupos registrados con búsqueda y filtro por semestre

#### Periodos UI

Los periodos de disponibilidad son dinámicos: se pueden agregar/quitar.
Cada periodo contiene:
- Hora inicio / Hora fin (Entry)
- Checkboxes para los 6 días de la semana
- Botón "Quitar"

#### Escalado (`_rescale_ui`)

La interfaz se redimensiona proporcionalmente al tamaño de la ventana,
usando como referencia 1920x1080.

#### Eventos principales

| Método                          | Propósito                                    |
|---------------------------------|----------------------------------------------|
| `evento_boton_profesores()`     | Guarda/actualiza profesor + disponibilidad   |
| `evento_materias()`             | Guarda materia con tipo                      |
| `evento_Salones()`              | Guarda salón                                 |
| `evento_grupos()`               | Guarda grupo con nivel (semestre)            |
| `eliminar_profesor()`           | Elimina profesor + disponibilidad + asignaciones |
| `eliminar_materia()`            | Elimina materia + asignaciones               |
| `eliminar_salon()`              | Elimina salón + horarios                     |
| `eliminar_grupo()`              | Elimina grupo + asignaciones + horarios      |
| `cargar_profesor_seleccionado()`| Carga datos del profesor al hacer clic en tabla|
| `cargar_materia_seleccionada()` | Carga datos de la materia (incluye tipo)     |
| `cargar_salon_seleccionado()`   | Carga datos del salón                        |
| `cargar_grupo_seleccionado()`   | Carga datos del grupo                        |
| `mostrar_datos_profesor()`      | Refresca la tabla de profesores              |
| `mostrar_datos_materias()`      | Refresca la tabla de materias                |
| `mostrar_datos_salones()`       | Refresca la tabla de salones (filtra MEDIACION_TECNOLOGICA) |
| `mostrar_datos_grupos()`        | Refresca la tabla de grupos                  |
| `filtrar_profesores()`          | Filtra tabla de profesores por texto         |
| `filtrar_materias()`            | Filtra materias por texto + semestre         |
| `filtrar_grupos()`              | Filtra grupos por texto + semestre           |

---

### 6.12 `src/UI/ventana_gestion.py` — Interfaz de Gestión y Horarios

**Clase:** `VentanaGestion`

#### Pestaña Gestionar (pes0)

**Filtros superiores:** Periodo (A / B) y Semestre.

**Panel izquierdo — Asignación por Periodos:**
- Campos de profesor (No. Cuenta, Nombre) — solo lectura al cargar desde la tabla derecha.
- Botón "Limpiar" para deseleccionar profesor.
- Etiqueta de resumen de horas (asignadas / disponibles / restantes) con cambio de color si hay sobrecarga.
- Tarjetas dinámicas de periodo, cada una contiene:
  - Horario editable (hora_inicio / hora_fin).
  - Combo de **Modalidad** (Presencial / Mediacion Tecnologica).
  - Etiqueta de horas restantes (se actualiza al seleccionar materia).
  - Filas de Materia + Grupo con botón "+ Agregar Materia" (múltiples filas por periodo).
  - Checkboxes de días (Lunes a Sábado).
  - Etiqueta de alerta (confirmación/error al guardar).
  - Botón "Guardar Asignaciones" — persiste disponibilidad, modalidad y asignación.
  - Botón "Quitar Periodo".
  - Separador visual debajo del botón guardar.
- Botón "+ Agregar Periodo" para periodos adicionales.

**Panel derecho — Profesores:**
- Tabla seleccionable con No. Cuenta, Nombre y Disponibilidad resumida.
- Búsqueda por texto sobre la tabla (filtro dinámico).
- Al hacer clic, carga los datos en el panel izquierdo.
- Al cargar, se limpian los periodos dummy (07:00-07:30) que el Personal anterior pudiera haber creado.

**Vista Previa de Asignaciones:**
- Filtro por estado (Todos / pendiente / asignado).
- Barra de búsqueda por texto (filtra por profesor o materia).
- Tabla con todas las asignaciones (LEFT JOIN con profesores, materias y grupos), ordenadas por ID.
- Botón "Limpiar" para resetear filtros.

**Acciones:**
- Botón "Liberar": libera la asignación seleccionada (borra horarios, vuelve a pendiente).
- Botón "Borrar Todas": elimina todas las asignaciones y horarios, resetea AUTO_INCREMENT.

#### Pestaña Alertas (pes_alertas)

Tercera pestaña que muestra **todas** las alertas generadas durante la asignación automática:

- **Tabla superior** con columnas: Materia, Grupo, Profesor, Causa.
- **Panel de detalle inferior** (Text widget) con: causas, sugerencias y detalles técnicos (horas requeridas, disponibilidad, slots ocupados, salones compatibles).
- Al seleccionar una alerta en la tabla, se muestra el detalle completo.
- Botón "Limpiar Alertas".
- Al finalizar una asignación automática con conflictos, el messagebox redirige a esta pestaña.

#### Pestaña Ver Horarios (pes1)

Visualización gráfica con matplotlib:

- **Modos**: Salón / Profesor / Grupo
- **Filtro por semestre** (solo para modo Grupo)
- **Navegación**: Anterior / Siguiente / Selección directa
- **Exportación**: PDF (completo), PNG (vista actual), Excel (multi-hoja)
- El gráfico muestra una tabla semanal con bloques de colores para cada clase

#### Métodos clave de VentanaGestion

| Método                          | Propósito                                    |
|---------------------------------|----------------------------------------------|
| `iniciar_asignacion_automatica()`| Ejecuta GeneradorHorarios en un hilo (con `separacion_online_activa=False`) |
| `borrar_asignacion_seleccionada()`| Elimina asignación y libera horario       |
| `formatear_asignaciones()`      | Borra TODAS las asignaciones y horarios (resetea AUTO_INCREMENT) |
| `actualizar_vista_previa()`     | Refresca la tabla de asignaciones con filtros (LEFT JOIN grupos) |
| `actualizar_tabla_grafica()`    | Dibuja el horario en matplotlib              |
| `exportar_pdf_completo()`       | Genera PDF de todos los horarios (blanco y negro) |
| `guardar_captura()`             | Guarda PNG del horario actual                |
| `exportar_excel()`              | Genera Excel multi-hoja con pandas+openpyxl  |
| `_agregar_periodo_asignacion(datos)` | Construye tarjeta de periodo (horario, modalidad, días, materia/grupo) |
| `_cargar_periodos_desde_bd()`   | Carga periodos+asignaciones desde BD (optimizado: 1 conexión, 3 queries) |
| `_guardar_disponibilidad_periodo()` | Guarda disponibilidad con modalidad       |
| `_asignar_periodo()`            | Inserta/modifica/sustituye asignación con periodo, hora_i, hora_f, modalidad |
| `_calcular_horas_profesor()`    | Suma horas disponibles vs asignadas           |
| `_calcular_horas_con_ui()`      | Calcula horas considerando cambios UI        |
| `_materias_filtradas_actual()`  | Filtra materias por Periodo+Semestre         |
| `_poblar_tabla_profesores()`    | Pobla la tabla seleccionable de profesores   |
| `_filtrar_tabla_profesores()`   | Filtra dinámicamente la tabla de profesores  |
| `obtener_o_crear_grupo()`       | Busca o crea grupo en BD automáticamente     |
| `_construir_pestana_alertas()`  | Construye la interfaz de la pestaña Alertas  |
| `_mostrar_alertas_en_tabla()`   | Puebla la tabla de alertas con resultados    |
| `_mostrar_detalle_alerta()`     | Muestra detalle completo de la alerta seleccionada |

#### Grupos por semestre

El método `_cargar_grupos_desde_bd()` determina el semestre de cada grupo:
1. Intenta regex `S(\d)` (ej. "S3A" → semestre 3)
2. Si no coincide, busca el grupo en el fallback `_grupos_fallback()`
3. Combina grupos de BD con los del fallback

---

## 7. FLUJO COMPLETO: CICLO DE VIDA DE UNA ASIGNACIÓN

```
1. [Personal] Registrar profesor con disponibilidad (días y horarios)
2. [Personal] Registrar materia con horas, tipo y preferencia
3. [Personal] Registrar salón con tipo
4. [Personal] Registrar grupos con nivel (semestre)
5. [Gestión]  Seleccionar Periodo (A o B) y Semestre en filtros superiores
6. [Gestión]  Seleccionar profesor en la tabla derecha
              → Se cargan sus periodos de disponibilidad + asignaciones en el panel izquierdo
7. [Gestión]  En cada tarjeta de periodo:
              a. Ajustar horario inicio/fin
              b. Elegir Modalidad (Presencial / Mediacion Tecnologica)
              c. Marcar días disponibles
              d. Elegir Materia + Grupo (múltiples filas por periodo)
              e. Click "Guardar Asignaciones"
              → Persiste disponibilidad con modalidad y crea asignación con estado 'pendiente'
8. [Gestión]  Ejecutar asignación automática:
              a. Motor calcula slots disponibles
              b. Busca mejor combinación de días/horarios/salones
              c. Usa salones MEDIACION_TECNOLOGICA para modalidad en línea
              d. Guarda en tabla horarios
              e. Marca asignación como 'asignado'
              f. Reporta conflictos en pestaña Alertas (detalle completo)
9. [Ver Horarios] Visualizar horarios generados (Salón / Profesor / Grupo)
10.[Ver Horarios] Exportar a PDF, PNG o Excel
```

---

## 8. REGLAS DE NEGOCIO IMPORTANTES

### 8.1 Profesores en línea / Mediación Tecnológica
- Ya no se usa el sufijo "-L" ni el campo `en_linea`.
- La modalidad "Mediacion Tecnologica" se asigna por periodo (en cada tarjeta).
- Deben usar salones cuyo ID empiece por "MEDIACION_TECNOLOGICA" (se auto-crean si hacen falta).
- Deben respetar separación de 2.5h después de clases presenciales del mismo profesor (regla desactivada por defecto).
- El profesor se identifica por `no_cuenta` (ya no se genera con sufijos).

### 8.2 Materias
- Tipo "Laboratorio": requiere salón tipo Laboratorio (teoría en Normal, práctica en Lab)
- Tipo "Tecnológica": requiere salón tipo Tecnológica
- Tipo "Normal": puede usar cualquier salón
- Tipo "Auditorio": requiere exclusivamente salón tipo Auditorio

### 8.3 Asignaciones
- Una misma combinación profesor-materia-grupo-modalidad no puede duplicarse
- Cada asignación tiene: `periodo` (A/B), `modalidad` (Presencial/Mediacion Tecnologica), `hora_inicio`, `hora_fin`, `estado` (pendiente/asignado)
- Las asignaciones se crean desde tarjetas de periodo que también persisten la disponibilidad horaria en `profesor_disponibilidad`
- Si la misma materia+grupo ya está asignada a otro profesor, se pregunta si desea sustituirlo
- Al liberar una asignación se borran sus horarios y vuelve a "pendiente"
- Al resetear se borran todas las asignaciones y horarios (resetea AUTO_INCREMENT)

### 8.4 Grupos
- Los grupos se almacenan en tabla `grupos` con `(grupo_id, nivel)` — se eliminó la columna `nombre`
- El `nivel` se usa para filtrar y asociar grupos a semestres
- Los grupos se gestionan desde la pestaña Personal (formulario + tabla + filtro por semestre + botón Eliminar)
- En la pestaña Gestión, los grupos se seleccionan dentro de cada tarjeta de periodo mediante combos
- Si un grupo no existe en BD al guardar asignación, se crea automáticamente (`obtener_o_crear_grupo()`)

---

## 9. EXPORTACIÓN DE DATOS

### PDF
- Exporta todos los horarios (según filtro actual) a un solo archivo PDF
- Se guarda en ~/Downloads/
- Modo blanco y negro para impresión

### PNG
- Captura el horario actualmente visible
- Se guarda en ~/Downloads/

### Excel
- Exporta todos los horarios como hojas individuales en un archivo .xlsx
- Cada entidad (salón/profesor/grupo) es una hoja (nombre recortado a 31 caracteres)
- Auto-ajusta el ancho de columnas (máximo 40)
- Requiere pandas y openpyxl

---

## 10. NOTAS TÉCNICAS

### PyInstaller
El proyecto incluye configuración para compilar a .exe con PyInstaller:
```bash
pyinstaller arrancar.spec
```

### Manejo de rutas
`ruta_recurso()` maneja tanto ejecución normal como empaquetada (sys._MEIPASS):

```python
def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS  # PyInstaller
    except Exception:
        base_path = os.path.abspath(...)
    return os.path.join(base_path, relative_path)
```

### Singleton de memoria gráfica
`memoria_Horario_Grafico.py` exporta una instancia global (`instancia`) y
referencias directas (`tensor_actual`, `entidades_actuales`, `modo_actual`)
para acceso rápido desde `ventana_gestion.py`.

---

## 11. HISTORIAL DE CAMBIOS

### 11.1 Permitir mismo horario para diferentes grupos (2026-06-17)

**Archivo:** `src/motor_horarios.py`

Se eliminó la verificación de `ocupacion_grupos` en `es_posible_asignar()`.
Ahora el motor permite que distintos grupos tengan clases en el mismo slot
horario, siempre que sea en **distinto salón** y el **profesor no esté ocupado**.
Esto refleja el escenario real donde múltiples grupos pueden tener clase a la
misma hora en diferentes aulas.

### 11.2 Barra de búsqueda de profesores en Gestión (2026-06-17)

**Archivo:** `src/UI/ventana_gestion.py`

Se agregó un campo "Buscar:" sobre el combobox de profesores en el panel
izquierdo de la pestaña Gestionar. Al escribir, filtra dinámicamente la
lista de profesores por nombre o ID (método `_filtrar_profesores_combo`).

### 11.3 Vista previa sin límite de registros (2026-06-17)

**Archivo:** `src/UI/ventana_gestion.py`

Se reemplazó `LIMIT 50` por `ORDER BY a.asignacion_id` en la consulta SQL
de `actualizar_vista_previa()`. Ahora se muestran todas las asignaciones sin
límite, ordenadas por ID de asignación.

### 11.4 Tipo de materia "Auditorio" (2026-06-17)

**Archivos:** `src/UI/ventana_principal.py`, `src/motor_horarios.py`

- Se agregó `"Auditorio"` como opción en el combobox de preferencia de materia
  y en el combobox de tipo de salón.
- En el motor (`motor_horarios.py`), cuando una materia es tipo `auditorio`,
  se buscan exclusivamente salones de tipo `Auditorio` para la asignación.
- El registro de materias y salones acepta "Auditorio" sin cambios adicionales.

### 11.5 Visualización de materias Auditorio en todos los grupos del semestre (2026-06-17)

**Archivo:** `src/clases/memoria_Horario_Grafico.py`

Cuando una materia es tipo `Auditorio`, el horario asignado a un grupo (ej. S9)
ahora se replica visualmente a todos los demás grupos del mismo semestre
(ej. SX, SW para semestre 9). Esto refleja que la clase en auditorio es
conjunta para todos los grupos.

El mapeo semestre→grupos está definido en la constante `GRUPOS_POR_SEMESTRE`
y la función `_semestre_de_grupo()` extrae el semestre del ID del grupo
mediante regex `S(\d)` o lookup en el mapa.

### 11.6 Pestaña de Alertas detalladas (2026-06-17)

**Archivos:** `src/motor_horarios.py`, `src/UI/ventana_gestion.py`

Se agregó una tercera pestaña **"Alertas"** en la ventana de Gestión que
almacena y muestra TODAS las alertas generadas durante la asignación
automática, sin límite de 5.

Cada alerta contiene:
- **Materia, Grupo y Profesor** involucrados.
- **Causas** detalladas del fallo (sobrecarga, falta de salones,
  disponibilidad insuficiente, etc.).
- **Sugerencias** de solución.
- **Detalles técnicos**: horas requeridas vs. disponibles, slots
  ocupados del profesor, lista de salones compatibles que tienen
  espacio libre, etc.

Al seleccionar una alerta en la tabla superior, se muestra el detalle
completo en el panel de texto inferior. Además, el messagebox ya no
trunca las alertas a 5 — solo muestra un resumen y redirige a la
pestaña Alertas.

### 11.7 Optimización de lotes: misma materia en salón consecutivo (2026-06-17, corregido 2026-06-17)

**Archivo:** `src/motor_horarios.py`

Cuando un profesor imparte la **misma materia** a **múltiples grupos**,
el motor ahora detecta esta situación y reutiliza el mismo salón para
colocar los grupos **consecutivamente** (uno detrás de otro).

**Antes (v1 - fallback):** El motor intentaba asignar cada grupo
de forma independiente. Si los grupos 2, 3, 4 lograban asignarse
en diferentes salones, el batch (colocación consecutiva) nunca se
activaba porque solo funcionaba como retry tras fallo.

**Ahora (v2 - prioridad):** El batch se implementa como estrategia
**prioritaria**: antes de cualquier intento de asignación independiente,
si ya existe una asignación previa del mismo (profesor+materia), el
motor primero intenta colocar el nuevo grupo **adyacente** (ANTES o
DESPUÉS) en el mismo salón. Esto garantiza que todos los grupos de
la misma materia compartan salón consecutivamente, sin depender de
fallos previos.

**Flujo actual:**
1. **[Batch prioritario]** Si el par (profesor, materia) ya tiene horarios previos → intentar colocar adyacente en el mismo salón.
2. **[Asignación normal]** Si el batch no fue posible (slot ocupado), intentar asignación independiente.
3. **[Batch fallback]** Si la asignación normal falló, reintentar batch como último recurso.

**Estructura:**
```python
# 1) Prioridad: colocar junto a asignaciones previas del mismo par
if key in _batch_map and not es_en_linea and tipo_materia not in ('laboratorio', 'auditorio'):
    _intentar_batch()

if not asignado_completamente:
    ...  # asignación normal (online, lab, presencial)

# 2) Fallback: reintentar batch solo si todo lo demás falló
if not asignado_completamente and not es_en_linea and tipo_materia not in ('laboratorio', 'auditorio'):
    _intentar_batch()

# 3) Registrar nuevos horarios en el batch_map
if asignado_completamente:
    _batch_map[key].extend(horarios_generados[gen_prev:])
```

### 11.8 Toggle de regla de separación 2.5h para clases en línea (2026-06-17)

**Archivos:** `src/motor_horarios.py`, `src/UI/ventana_gestion.py`

Se agregó un Checkbutton "Regla 2.5h (online tras presencial)" en el panel
de acciones de la pestaña Gestionar. Cuando está desactivado, el motor ignora
la regla que obliga a que una clase en línea comience 2.5h después de la
última clase presencial del mismo profesor.

**Comportamiento:**
- Activado (default): se aplica la regla de separación (comportamiento original).
- Desactivado: las clases en línea pueden asignarse en cualquier slot dentro
  de la disponibilidad del profesor, sin importar sus clases presenciales.

---

### 11.9 Auto-generación de profesor_id (P0001…) y nuevo campo no_cuenta (2026-06-22)

**Archivos:** `src/clases/validacion_bd.py`, `src/clases/profesor.py`, `src/UI/ventana_principal.py`

- `profesor_id` ahora se auto-genera como `P0001`, `P0002`… (VARCHAR, mediante `MAX(SUBSTRING) + 1`).
- Se eliminó la lógica de `en_linea` del modelo y editor de profesores.
- Se agregó el campo `no_cuenta` como identificador proporcionado por el usuario.
- Los títulos (DR., MTRO., ING., LIC., etc.) se separan automáticamente del nombre al guardar.

### 11.10 Nuevo modelo de grupos (grupo_id + nivel) (2026-06-22)

**Archivos:** `src/clases/grupo.py`, `src/UI/ventana_principal.py`, `src/UI/ventana_gestion.py`, `src/clases/memoria_Horario_Grafico.py`, `migrar_grupos.sql`

- Nueva tabla `grupos` con columnas `(grupo_id, nivel)`; se eliminó la columna `nombre`.
- Migración `migrar_grupos.sql` para agregar `nivel` a la tabla existente.
- La pestaña Personal ahora tiene una sección de Grupos con formulario + tabla + filtro por semestre.
- `ventana_gestion.py` lee `nivel` desde la BD y actualizó `obtener_o_crear_grupo`.
- `memoria_Horario_Grafico.py` carga `GRUPOS_POR_SEMESTRE` desde BD en lugar de un diccionario fijo.

### 11.11 Rediseño completo de la pestaña Gestionar (2026-06-22)

**Archivo:** `src/UI/ventana_gestion.py`

**Filtros superiores:** Solo Periodo (A / B) y Semestre; se eliminó el combo de Grupo.

**Panel izquierdo — Asignación por Periodos:**
- Campos de profesor (No. Cuenta, Nombre) en modo solo lectura al cargar desde la tabla.
- Etiqueta de resumen de horas (asignadas / disponibles / restantes).
- Tarjetas dinámicas de periodo, cada una contiene:
  - Horario editable (hora_inicio / hora_fin).
  - Checkboxes de días (Lunes a Sábado).
  - Filas de Materia + Grupo con botón "+ Agregar Materia".
  - Botón "Guardar Asignaciones" que persiste disponibilidad y asignaciones.
  - Separador visual debajo del botón guardar.
- Botón "+ Agregar Periodo" para añadir periodos vacíos.

**Panel derecho — Tabla de Profesores seleccionable:**
- Búsqueda por texto sobre la tabla.
- Al hacer clic en un profesor, se cargan sus datos en el panel izquierdo.
- Columna de disponibilidad resumida.

**Tabla de Vista Previa:**
- Filtro por estado (Todos / pendiente / asignado).
- Búsqueda por texto (filtra por nombre de profesor o materia).
- Muestra todas las asignaciones ordenadas por ID.

**Acciones:**
- Checkbox "Regla 2.5h (online tras presencial)".
- Botón "Liberar": libera la asignación seleccionada.
- Botón "Borrar Todas": elimina todas las asignaciones y horarios.

**Métodos nuevos:**
- `_agregar_periodo_asignacion(datos)` — construye una tarjeta de periodo con horario, días, materia/grupo y guardar.
- `_cargar_periodos_desde_bd()` — carga periodos desde `profesor_disponibilidad` agrupados por hora_i/hora_f.
- `_guardar_disponibilidad_periodo()` — guarda/actualiza la disponibilidad del profesor.
- `_asignar_periodo()` — inserta asignación con periodo y estado 'pendiente'.
- `_actualizar_horas_info()` / `_calcular_horas_profesor()` — muestra resumen de horas.
- `_materias_filtradas_actual()` — filtra materias por Periodo y Semestre seleccionados.
- `_poblar_tabla_profesores()` / `_filtrar_tabla_profesores()` — gestiona la tabla de profesores.

### 11.12 Backup del motor y copia para adaptación (2026-06-22)

**Archivos:** `src/motor_horarios_backup.py`, `src/motor_horarios_nuevo.py`

- Se creó `motor_horarios_backup.py` como copia exacta del original.
- Se creó `motor_horarios_nuevo.py` como copia para adaptar al nuevo esquema de periodos.
- El motor original (`motor_horarios.py`) permanece intacto.

### 11.13 Migración columna periodo en asignaciones (2026-06-22)

**Archivos:** `migrar_asignaciones_periodo.sql`

- Agrega columna `periodo VARCHAR(10) NOT NULL DEFAULT 'A'` a la tabla `asignaciones`.
- El combo de periodo usa valores cortos `"A"` / `"B"` (se corrigió de los anteriores `"A (Septiembre-Octubre)"`, que excedían el límite de 10 caracteres).

### 11.14 Correcciones visuales y de flujo en Gestión (2026-06-22)

- Reorden de elementos en tarjetas de periodo: días → botón guardar → separador.
- Inicialización de la tabla de vista previa al abrir la pestaña (`self.ventana.after(100, self.actualizar_vista_previa)`).
- Eliminación de widgets y métodos obsoletos (`combo_profesores`, `combo_materias`, `combo_grupos`, `combo_semestre`, `asignar_profesor_materia`, etc.).
- Corrección de `ttk.LabelFrame`: quitados parámetros no soportados (`foreground`, `font`).
- Corrección de closure: `btn_agregar_mat` creado antes que `agregar_fila_asignacion` para evitar error de referencia.

### 11.15 Carga de asignaciones existentes en tarjetas de periodo (2026-06-22)

**Archivos:** `migrar_asignaciones_periodo.sql`, `src/UI/ventana_gestion.py`

- Se agregaron columnas `hora_inicio TIME` y `hora_fin TIME` a la tabla `asignaciones`.
- `_asignar_periodo()` ahora almacena `hora_i`/`hora_f` al guardar la asignación.
- `_cargar_periodos_desde_bd()` ahora consulta también las asignaciones del profesor (con `LEFT JOIN materias` para obtener el nombre) y las agrupa por horario.
- `_agregar_periodo_asignacion()` recibe las asignaciones existentes en `datos['asignaciones']` y pre-puebla los combos de materia/grupo con `agregar_fila_asignacion(mat_inicial, grp_inicial)`.
- Al seleccionar un profesor, las materias y grupos ya asignados aparecen precargados en cada tarjeta de periodo.

### 11.16 Optimización de rendimiento al cargar profesor (2026-06-22)

**Archivo:** `src/UI/ventana_gestion.py`

**Problema:** Al seleccionar un profesor se abrían múltiples conexiones DB (~10) con ~15 consultas SQL, causando latencia notable.

**Optimizaciones:**
- `_nombre_de_materia()` (una consulta DB por asignación) se reemplazó por un `LEFT JOIN materias` en la misma consulta que trae las asignaciones.
- `_calcular_horas_profesor()` se invocaba una vez por cada tarjeta de periodo; ahora se calcula una sola vez en `_cargar_periodos_desde_bd` y se pasa como `horas_pre` a todas las tarjetas.
- Las listas `todos_grupos` y `mat_ids` se construían repetidamente dentro de cada tarjeta; ahora se construyen una vez y se pasan como `grupos_pre`/`materias_pre`.

**Resultado:** 1 conexión DB (antes ~10), 3 consultas SQL (antes ~15).

### 11.17 Sección Grupos en Personal + filtros por semestre (2026-06-22)

**Archivos:** `src/UI/ventana_principal.py`, `src/clases/grupo.py`, `arrancar.py`

- Nueva **sección Grupos** en el panel izquierdo de la pestaña Personal con campos Grupo (ID), Semestre y botones Agregar/Eliminar.
- Nuevo modelo `src/clases/grupo.py` con clase `grupo(grupo_id, nivel)` que inserta o actualiza en BD.
- Nuevas tablas de datos: Grupos Registrados con búsqueda por texto y filtro por semestre.
- Filtro por semestre añadido también a la tabla de Materias.
- Botones "Eliminar" para Profesores, Materias y Salones con eliminación en cascada (borra asignaciones y horarios asociados).
- `arrancar.py` ahora llama a `app.mostrar_datos_grupos()` para cargar grupos al inicio.
- Al cargar salones en tabla, se filtran automáticamente los `MEDIACION_TECNOLOGICA` (solo se muestran salones físicos).

### 11.18 Columna modalidad en asignaciones y disponibilidad (2026-06-22)

**Archivos:** `migrar_modalidad_periodo.sql`, `migrar_asignaciones_periodo.sql`, `migrar_grupos.sql`

- `migrar_modalidad_periodo.sql`: Agrega columna `modalidad VARCHAR(30) NOT NULL DEFAULT 'Presencial'` a `profesor_disponibilidad`.
- `migrar_asignaciones_periodo.sql`: Agrega columna `modalidad VARCHAR(30) NOT NULL DEFAULT 'Presencial'` a `asignaciones` (después de `hora_fin`).
- `migrar_grupos.sql`: También incluye la adición de `modalidad` a `asignaciones`.

### 11.19 Renombrado EN_LINEA → MEDIACION_TECNOLOGICA (2026-06-22)

**Archivos:** `migrar_salones_mediacion.sql`, `src/motor_horarios.py`, `src/UI/ventana_principal.py`

- Nuevo script `migrar_salones_mediacion.sql` que renombra todos los salones `EN_LINEA_*` a `MEDIACION_TECNOLOGICA_*` y actualiza los horarios existentes.
- En `motor_horarios.py`: todas las referencias a `EN_LINEA` se cambiaron a `MEDIACION_TECNOLOGICA`.
- El motor ahora **auto-crea** salones `MEDIACION_TECNOLOGICA_N` si el número de asignaciones en línea excede la cantidad de salones existentes.

### 11.20 Pestaña Alertas con detalle completo (2026-06-22)

**Archivos:** `src/UI/ventana_gestion.py`, `src/motor_horarios.py`

- Nueva tercera pestaña **"Alertas"** en VentanaGestion (después de Gestionar, antes de Ver Horarios).
- Tabla superior con columnas Materia, Grupo, Profesor, Causa.
- Panel de texto inferior con detalle completo: causas numeradas, sugerencias y detalles técnicos (horas requeridas, disponibilidad del profesor, slots ocupados, salones compatibles).
- Al finalizar asignación automática con conflictos, el messagebox muestra resumen y redirige a la pestaña Alertas.
- Se eliminó el límite de 5 alertas en el messagebox.

### 11.21 Modalidad en tarjetas de periodo y combo en UI (2026-06-22)

**Archivo:** `src/UI/ventana_gestion.py`

- Cada tarjeta de periodo ahora incluye un combo **Modalidad** con opciones "Presencial" y "Mediacion Tecnologica".
- `_guardar_disponibilidad_periodo()` guarda la modalidad en `profesor_disponibilidad`.
- `_asignar_periodo()` guarda la modalidad en `asignaciones`.
- La modalidad se carga desde BD al editar un profesor.
- Se eliminó el checkbox "Regla 2.5h (online tras presencial)" del panel de acciones. La regla ahora se controla mediante `separacion_online_activa = False` en `iniciar_asignacion_automatica()`.

### 11.22 Resolución de conflictos al asignar (2026-06-22)

**Archivo:** `src/UI/ventana_gestion.py` — método `_asignar_periodo()`

- Si la misma combinación materia+grupo+modalidad ya existe para el profesor actual: pregunta si desea modificar periodo/horario.
- Si la misma materia+grupo+periodo+modalidad está asignada a **otro profesor**: pregunta si desea sustituirla (transfiere asignación al nuevo profesor).
- Si no existe: crea asignación nueva con estado 'pendiente'.

### 11.23 Auto-creación de grupos desde Gestión (2026-06-22)

**Archivo:** `src/UI/ventana_gestion.py` — método `obtener_o_crear_grupo()`

- Al guardar una asignación con un grupo que no existe en BD, se crea automáticamente con el nivel correspondiente (extraído de `materias_map`).
- Evita que el usuario tenga que registrar grupos manualmente antes de asignar.

### 11.24 Exportación a Excel multi-hoja (2026-06-22)

**Archivo:** `src/UI/ventana_gestion.py` — método `exportar_excel()`

- Nueva función de exportación a Excel que genera un archivo `.xlsx` con una hoja por cada entidad (salón/profesor/grupo).
- Cada hoja contiene la tabla horaria semanal (Hora, Lunes-Sábado).
- Los saltos de línea en celdas se reemplazan por " - ".
- Auto-ajuste de ancho de columnas (máximo 40 caracteres).
- Requiere `pandas` y `openpyxl`.

### 11.25 Optimización y limpieza en Gestión (2026-06-22)

**Archivo:** `src/UI/ventana_gestion.py`

- `_cargar_periodos_desde_bd()` ahora limpia automáticamente los periodos dummy `07:00-07:30` que el formulario de Personal podía crear por defecto.
- Vista previa ahora usa `LEFT JOIN grupos` para mostrar correctamente grupos que no existen en la tabla `grupos`.
- `cargar_combos_bd()` actualizado con `LEFT JOIN` para manejar datos huérfanos.
- Cálculo de horas mejorado con `_calcular_horas_con_ui()` que considera cambios en la UI antes de guardar.

### 11.26 Auditorio: visualización multi-grupo (2026-06-22)

**Archivos:** `src/clases/memoria_Horario_Grafico.py`

- Cuando una materia es tipo `Auditorio`, el horario asignado a un grupo se replica visualmente a todos los demás grupos del mismo semestre en el tensor.
- Los grupos por semestre se cargan dinámicamente desde BD (`_cargar_grupos_desde_bd()`) en lugar del diccionario fijo anterior.

### 11.27 Nuevo motor: solo asigna salones con optimización mismo-salón (2026-06-23)

**Archivos:** `src/motor_horarios_nuevo.py`, `src/UI/ventana_gestion.py`

- Se creó `motor_horarios_nuevo.py` con un algoritmo completamente reescrito.
- **Cambio fundamental:** el motor ya no genera horarios (días/horas) — esos vienen fijos desde la asignación (`hora_inicio`, `hora_fin`). Solo asigna salones.
- Para cada asignación, busca en `profesor_disponibilidad` los días donde el rango `[hora_inicio, hora_fin]` quepa dentro de la disponibilidad del profesor.
- Asigna salones compatibles según tipo de materia y modalidad (Presencial / Mediacion Tecnologica).
- **Optimización `salon_por_materia_profesor`:** si un profesor da la misma materia en varios grupos, el motor reusa el mismo salón para todos, evitando que el maestro tenga que cambiar de salón entre clases.
- Se eliminó toda la lógica de estrategias de distribución, batch, simétrico mixto y regla de separación 2.5h.
- `ventana_gestion.py` cambió su import de `src.motor_horarios` a `src.motor_horarios_nuevo`.
- Se agregó botón "Iniciar Asignaciones de Aula" en la barra de filtros de Gestión.

### 11.28 Correcciones en motor nuevo: normalización de días y distribución por horas_semana (2026-06-23)

**Archivos:** `src/motor_horarios_nuevo.py`

- **Normalización de días:** Se agregó `MAPA_NUM_A_DIA` y `_normalizar_dia()` para
  convertir los días numéricos (`"0"`–`"5"`) almacenados en `profesor_disponibilidad`
  a nombres en español (`"Lunes"`–`"Sábado"`) al cargar los datos. Esto corrigió que
  el motor asignara horarios en días incorrectos.
- **Distribución por `horas_semana`:** Se reescribió `_asignar_dias_a_salon()` para
  que calcule el número de sesiones semanales a partir de `horas_semana` de la materia:
  - `total_bloques = horas_semana × 2` (bloques de 30 min)
  - Si la ventana `hora_fin − hora_inicio` es mayor de lo necesario, recalcula
    la duración de cada sesión distribuyendo equitativamente entre los días
    disponibles (`session_blocks = max(ceil(total_bloques / num_dias), 4)`)
  - Cada sesión se coloca al inicio de la ventana (`hora_inicio`) y dura
    `session_blocks` bloques
- **Múltiples sesiones por día:** Si hay más sesiones necesarias que días
  disponibles, se apilan varias sesiones consecutivas en el mismo día (avanzando
  `slot_inicio + session_blocks` por cada una).
