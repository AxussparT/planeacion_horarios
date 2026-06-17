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
├── migrar_disponibilidad.sql        # Migración de disponibilidad multi-periodo
├── assets/
│   └── fondo.png                    # Imagen de fondo de la ventana
├── src/
│   ├── conexion.py                  # Conexión a MySQL
│   ├── motor_horarios.py            # Algoritmo de generación automática de horarios
│   ├── resp_motor.py                # (vacio - reservado)
│   ├── clases/
│   │   ├── __init__.py
│   │   ├── materia.py               # Modelo y guardado de materias
│   │   ├── profesor.py              # Modelo y guardado de profesores
│   │   ├── salon.py                 # Modelo y guardado de salones
│   │   ├── Validar_materia.py       # Validación y registro en BD de materias
│   │   ├── validacion_bd.py         # Validación y registro en BD de profesores
│   │   └── memoria_Horario_Grafico.py # Memoria/ tensor para visualización de horarios
│   └── UI/
│       ├── __init__.py
│       ├── ventana_principal.py     # Ventana principal (pestaña Personal)
│       └── ventana_gestion.py       # Ventana de gestión (pestañas Gestionar y Ver Horarios)
```

---

## 5. ARQUITECTURA

### 5.1 Flujo general

```
arrancar.py
    │
    ├── Crea VentanaPrincipal (tk.Tk)
    │       ├── Pestaña "Personal"   (tab_personal)
    │       │       ├── Panel izquierdo: formularios de Profesores, Materias, Salones
    │       │       └── Panel derecho: tablas de datos con búsqueda
    │       └── Pestaña "Gestión"    (tab_gestion)
    │               └── VentanaGestion (embebida)
    │                       ├── Pestaña "Gestionar": asignaciones manuales y automáticas
    │                       └── Pestaña "Ver Horarios": visualización gráfica (matplotlib)
    │
    └── mainloop()
```

### 5.2 Base de datos (bd_seso)

**Tablas principales:**

| Tabla                    | Propósito                                      |
|--------------------------|-------------------------------------------------|
| `profesores`             | Profesores (con variante -L para online)        |
| `profesor_disponibilidad`| Disponibilidad horaria por día (multi-periodo)  |
| `materias`               | Materias con horas, semestre y tipo             |
| `salones`                | Salones con capacidad y tipo                    |
| `grupos`                 | Grupos (SA, SU, S3A, etc.)                      |
| `asignaciones`           | Relación profesor-materia-grupo                 |
| `horarios`               | Horarios generados (salón, día, hora)           |
| `semestres`              | Catálogo de semestres                           |

---

## 6. DESCRIPCIÓN DETALLADA DE CADA ARCHIVO

### 6.1 `arrancar.py` — Punto de entrada

```python
# Crea la ventana raíz de Tkinter
root = tk.Tk()
# Asigna un ícono personalizado
icono = tk.PhotoImage(file=ruta_recurso('src/UI/logo ph.png'))
root.iconphoto(True, icono)
# Instancia la ventana principal
app = VentanaPrincipal(root)
# Carga datos iniciales en las tablas
app.mostrar_datos_profesor()
app.mostrar_datos_materias()
app.mostrar_datos_salones()
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
    def __init__(self, cuenta, nombre_completo, periodos, linea):
        # Delega en validar_y_registrar_profesor()
```

- `cuenta`: ID del profesor (ej. "P003" o "P003-L")
- `nombre_completo`: Nombre completo
- `periodos`: Lista de dicts con `{dias, hora_inicio, hora_fin}`
- `linea`: "Sí", "No" o "Ambos"

---

### 6.4 `src/clases/validacion_bd.py` — Validación y guardado de profesores

**Funciones:**

| Función                                | Propósito                                    |
|----------------------------------------|----------------------------------------------|
| `formatear_hora(hora_str)`             | Normaliza "7:00" → "07:00:00"               |
| `validar_y_registrar_profesor(...)`     | Inserta o actualiza profesor + disponibilidad|

**Lógica de `validar_y_registrar_profesor`:**

1. Verifica si el `profesor_id` ya existe en `profesores`
2. Si existe → actualiza nombre y campos base, borra y re-inserta `profesor_disponibilidad`
3. Si no existe → inserta en `profesores` y en `profesor_disponibilidad`
4. Guarda los periodos expandiendo cada día como fila individual en `profesor_disponibilidad`

---

### 6.5 `src/clases/materia.py` — Modelo Materia

```python
class materia:
    def __init__(self, clave, nombre, horas_semana, semestre, tipo):
```

- `tipo`: "Normal", "Tecnológica" o "Laboratorio"

Delega en `Validar_materia.validar_y_registrar_materia()`.

---

### 6.6 `src/clases/Validar_materia.py` — Validación y guardado de materias

**Función principal:** `validar_y_registrar_materia(clave, nombre, horas_semana, semestre, tipo)`

1. Verifica si la materia ya existe por `materia_id`
2. Si existe → pregunta si desea actualizar
3. Si no existe → inserta

---

### 6.7 `src/clases/salon.py` — Modelo Salón

```python
class salon:
    def __init__(self, numero_aula, capacidad, tipo):
```

Valida que capacidad sea numérico, luego inserta en tabla `salones`.

---

### 6.8 `src/motor_horarios.py` — ALGORITMO DE ASIGNACIÓN AUTOMÁTICA

**Clase principal:** `GeneradorHorarios`

#### 6.8.1 Concepto de SLOT

El día se divide en **30 slots** de 30 minutos cada uno, empezando a las 7:00 AM:

```
Slot  0 = 07:00
Slot  1 = 07:30
Slot  2 = 08:00
...
Slot 29 = 21:30
```

Conversiones: `_hora_a_slot()` y `_slot_a_hora()`.

#### 6.8.2 Matrices de ocupación

Tres diccionarios booleanos:

| Diccionario                    | Clave                          | Propósito               |
|-------------------------------|--------------------------------|-------------------------|
| `ocupacion_salones[dia,salon,slot]` | (str, str, int) → bool  | Salón ocupado?          |
| `ocupacion_profesores[dia,prof,slot]`| (str, str, int) → bool  | Profesor ocupado?       |
| `ocupacion_grupos[dia,grupo,slot]`  | (str, str, int) → bool  | Grupo ocupado?          |

#### 6.8.3 Flujo de `ejecutar(modo)`

```
ejecutar(modo)
  ├── cargar_datos(modo)        → Carga asignaciones, disponibilidad, salones
  ├── _limpiar_matrices()       → Resetea ocupación y uso_salones
  ├── [si modo=parcial] _cargar_horarios_existentes() → Marca horarios previos como ocupados
  ├── Ordenar asignaciones:
  │      1. Presenciales primero, online después
  │      2. Por semestre (menor primero)
  │      3. Tecnológicas/Laboratorio primero, Normal después
  │      4. Más horas primero
  │
    ├── Para cada asignación:
    │    ├── Calcular bloques_totales = horas_semana * 2
    │    ├── Generar estrategias de distribución
    │    │   (pares de días, cuádruples, o días individuales)
    │    │
    │    ├── [Batch prioritario]:
    │    │   Si el par (profesor_id, materia_id) ya tiene horarios
    │    │   previos → intentar colocar el nuevo grupo ANTES o DESPUÉS
    │    │   en el mismo salón (solo presencial, no lab/auditorio)
    │    │
    │    ├── [Si es EN LÍNEA]:
    │    │   ├── Buscar salones cuyo ID empiece con "EN_LINEA"
    │    │   ├── Intentar estrategia simétrica (mismo slot en todos los días)
    │    │   └── [fallback] Intentar bloque por bloque
    │    │
    │    ├── [Si es LABORATORIO]:
    │    │   ├── Buscar salones tipo Laboratorio + Normal
    │    │   ├── Intentar estrategia simétrica mixta (alterna salon normal/lab)
    │    │   └── [fallback] Intentar bloque por bloque
    │    │   └── [fallback 2] Intentar cualquier salón
    │    │
    │    ├── [Si es PRESENCIAL]:
    │    │   ├── Priorizar salones según tipo de materia
    │    │   ├── Intentar estrategia simétrica
    │    │   └── [fallback] Intentar bloque por bloque
    │    │
    │    ├── [Batch fallback]:
    │    │   Si la asignación normal falló y hay batch previo,
    │    │   reintentar colocación adyacente (solo presencial,
    │    │   no lab/auditorio)
    │    │
    │    └── [Si falló todo] → Generar alerta con diagnóstico
  │
  └── guardar_en_bd() → Inserta horarios y marca asignaciones como 'asignado'
```

#### 6.8.4 Estrategias de distribución

Para materias de 4h (8 bloques):

```python
[("Lunes", 4), ("Miércoles", 4)]   # 2h Lunes + 2h Miércoles
[("Martes", 4), ("Jueves", 4)]     # 2h Martes + 2h Jueves
... # y otras 17 combinaciones más
```

Para materias de 3h (6 bloques):
```python
[("Lunes", 4), ("Miércoles", 2)]   # 2h Lunes + 1h Miércoles
[("Lunes", 2), ("Miércoles", 4)]
...
```

#### 6.8.5 Regla de separación para clases en línea

Cuando un profesor tiene versión presencial (ID base) y online (ID + "-L"):
La clase online debe empezar **2.5 horas después** (5 slots) de la última clase
presencial del mismo profesor en ese día.

```python
if es_en_linea:
    base_prof_id = prof_id.replace('-L', '')
    max_slot_presencial = último slot presencial del día
    if slot_inicio < (max_slot_presencial + 5):
        return False  # No se puede asignar aquí
```

#### 6.8.6 Evaluación de slots (`_evaluar_slot`)

Asigna un puntaje a cada slot candidato:

| Condición                          | Puntaje |
|------------------------------------|---------|
| Grupo sin clases previas ese día   | 100 - slot_inicio |
| Slot adyacente a clase existente   | 200 (óptimo, evita huecos) |
| Slot contiguo a clase existente    | 150 |
| Slot lejano de otras clases        | -(distancia * 50) |

Se elige el slot con mayor puntaje.

#### 6.8.7 Diagnóstico de fallos

Cuando una asignación no se puede realizar, se genera un mensaje con:
- Causas identificadas (sobrecarga, falta de salones, disponibilidad insuficiente)
- Sugerencias de solución
- Debug en consola con los periodos reales del profesor y slots ocupados

---

### 6.9 `src/clases/memoria_Horario_Grafico.py` — Tensor de horarios para visualización

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

---

### 6.10 `src/UI/ventana_principal.py` — Interfaz de Personal

**Clase:** `VentanaPrincipal`

#### Pestaña Personal (tab_personal)

Panel izquierdo (con scroll):
- **Sección Profesores**: campos No. Cuenta, Nombre(s), Apellidos, combo En línea, periodos de disponibilidad, botones Guardar/Eliminar/Limpiar
- **Sección Materias**: campos Clave, Nombre, Horas Semana, Semestre, Prioridad
- **Sección Salones**: campos Número de aula, Capacidad, Tipo

Panel derecho:
- Tabla de profesores registrados con búsqueda
- Tabla de materias registradas con búsqueda y filtro por semestre
- Tabla de salones registrados

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
| `evento_materias()`             | Guarda materia                               |
| `evento_Salones()`              | Guarda salón                                 |
| `cargar_profesor_seleccionado()`| Carga datos del profesor al hacer clic en tabla|
| `cargar_materia_seleccionada()` | Carga datos de la materia                    |
| `cargar_salon_seleccionado()`   | Carga datos del salón                        |
| `mostrar_datos_profesor()`      | Refresca la tabla de profesores              |
| `mostrar_datos_materias()`      | Refresca la tabla de materias                |
| `mostrar_datos_salones()`       | Refresca la tabla de salones                 |

---

### 6.11 `src/UI/ventana_gestion.py` — Interfaz de Gestión y Horarios

**Clase:** `VentanaGestion`

#### Pestaña Gestionar (pes0)

Panel izquierdo: combos para seleccionar Periodo, Profesor, Materia, Grupo, Semestre,
y botones de acción (Asignación Manual, Automática, Liberar, Borrar Todo).

Panel derecho:
- Filtro por estado (Todos / pendiente / asignado)
- Barra de búsqueda por texto (filtra por nombre de profesor o materia)
- Tabla de asignaciones con scroll horizontal y vertical
- Al seleccionar una fila, carga los datos en los combos del panel izquierdo

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
| `asignar_profesor_materia()`    | Crea/modifica una asignación manual          |
| `iniciar_asignacion_automatica()`| Ejecuta GeneradorHorarios en un hilo        |
| `borrar_asignacion_seleccionada()`| Elimina asignación y libera horario       |
| `formatear_asignaciones()`      | Borra TODAS las asignaciones y horarios      |
| `actualizar_vista_previa()`     | Refresca la tabla de asignaciones con filtros|
| `cargar_combos_bd()`            | Pobla los combos desde la BD                 |
| `cargar_grupos_por_semestre()`  | Filtra grupos disponibles por semestre       |
| `actualizar_tabla_grafica()`    | Dibuja el horario en matplotlib              |
| `exportar_pdf_completo()`       | Genera PDF de todos los horarios             |
| `guardar_captura()`             | Guarda PNG del horario actual                |
| `exportar_excel()`              | Genera Excel multi-hoja                      |

#### Grupos por semestre

El método `_cargar_grupos_desde_bd()` determina el semestre de cada grupo:
1. Intenta regex `S(\d)` (ej. "S3A" → semestre 3)
2. Si no coincide, busca el grupo en el fallback `_grupos_fallback()`
3. Combina grupos de BD con los del fallback

---

## 7. FLUJO COMPLETO: CICLO DE VIDA DE UNA ASIGNACIÓN

```
1. [Personal] Registrar profesor con disponibilidad (días y horarios)
2. [Personal] Registrar materia con horas y tipo
3. [Personal] Registrar salón con tipo
4. [Gestión]  Crear asignación: seleccionar profesor + materia + grupo
5. [Gestión]  Ejecutar asignación automática:
              a. Motor calcula slots disponibles
              b. Busca mejor combinación de días/horarios/salones
              c. Guarda en tabla horarios
              d. Marca asignación como 'asignado'
              e. Reporta conflictos si los hay
6. [Ver Horarios] Visualizar horarios generados
```

---

## 8. REGLAS DE NEGOCIO IMPORTANTES

### 8.1 Profesores en línea
- Se crean con ID base + "-L" (ej. "P003-L")
- Deben usar salones con ID que empiece por "EN_LINEA"
- Deben respetar separación de 2.5h después de clases presenciales del mismo profesor base
- (No hay restricción de horario matutino/vespertino fijo)

### 8.2 Materias
- Tipo "Laboratorio": requiere salón tipo Laboratorio (teoría en Normal, práctica en Lab)
- Tipo "Tecnológica": requiere salón tipo Tecnológica
- Tipo "Normal": puede usar cualquier salón

### 8.3 Asignaciones
- Una misma combinación profesor-materia-grupo no puede duplicarse
- Cada asignación puede tener estado "pendiente" o "asignado"
- Al liberar una asignación se borran sus horarios y vuelve a "pendiente"
- Al resetear se borran todas las asignaciones y horarios

### 8.4 Grupos
- El semestre se deduce del grupo mediante regex `S(\d)` o por lookup en fallback
- Los grupos se comparten entre presencial y online
- Los grupos se listan en el combo según el semestre seleccionado y la materia

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
- Cada entidad (salón/profesor/grupo) es una hoja
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
