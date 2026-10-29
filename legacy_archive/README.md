# Carpeta de Archivo Histórico (Legacy)

Esta carpeta contiene archivos y motores anteriores que han sido archivados para mantener el proyecto limpio y ordenado:

- motores/motor_horarios_nuevo.py: Versión experimental con detección de grafos de conflictos y ventanas compartidas (desactivada).
- motores/motor_horarios_backup.py: Respaldo previo del motor de asignación.
- motores/motor_horarios_anterior.py: Versión histórica original conectada a MySQL.
- motores/resp_motor.py: Archivo vacío reservado.
- saga.db: Archivo temporal vacío (la base real opera en %LOCALAPPDATA%\SAGA\saga.sqlite3).

El sistema activo ahora utiliza de forma limpia y directa:
- src/motor_horarios.py: Motor principal simplificado para asignación de salones y horarios.
- src/motor_preasignacion.py: Motor de preasignación de grupos y materias en aulas.
