import mysql.connector

conn = mysql.connector.connect(
    host="localhost", user="root", password="123456",
    database="bd_seso", port='3306'
)
cur = conn.cursor(dictionary=True)

print("=== 1) SHOW CREATE TABLE horarios ===")
cur.execute("SHOW CREATE TABLE horarios")
row = cur.fetchone()
print(row['Create Table'])

print("\n=== 2) SHOW TRIGGERS ===")
cur.execute("SHOW TRIGGERS")
triggers = cur.fetchall()
if triggers:
    for t in triggers:
        print(f"  Trigger: {t['Trigger']}")
        print(f"  Event: {t['Event']}")
        print(f"  Table: {t['Table']}")
        print(f"  Statement: {t['Statement'][:200]}")
        print()
else:
    print("  (no triggers)")

print("\n=== 3) SHOW COLUMNS FROM horarios ===")
cur.execute("SHOW COLUMNS FROM horarios")
for row in cur.fetchall():
    print(f"  {row['Field']:20} {row['Type']:30} {row['Extra']}")

print("\n=== 4) DATA ACTUAL EN HORARIOS ===")
cur.execute("SELECT horario_id, salon_id, HEX(dia) AS dia_hex, dia, hora_inicio, hora_fin FROM horarios ORDER BY horario_id")
for row in cur.fetchall():
    print(f"  id={row['horario_id']} salon={row['salon_id']!r} dia_hex={row['dia_hex']!r} dia={row['dia']!r} ini={row['hora_inicio']} fin={row['hora_fin']}")

print("\n=== 5) INSERT MANUAL DE PRUEBA ===")
try:
    cur.execute("INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin) VALUES (1, 'f18', 'TEST0', '07:00:00', '09:00:00')")
    conn.commit()
    print("  Insertado con dia='TEST0'")
    cur.execute("SELECT horario_id, salon_id, HEX(dia) AS dia_hex, dia FROM horarios WHERE dia = 'TEST0'")
    row = cur.fetchone()
    if row:
        print(f"  LEIDO: id={row['horario_id']} dia_hex={row['dia_hex']!r} dia={row['dia']!r}")
    else:
        print(f"  NO ENCONTRADO con dia='TEST0', buscando el ultimo insertado...")
        cur.execute("SELECT horario_id, salon_id, HEX(dia) AS dia_hex, dia FROM horarios ORDER BY horario_id DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            print(f"  LEIDO: id={row['horario_id']} dia_hex={row['dia_hex']!r} dia={row['dia']!r}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== 6) PROFESOR_DISPONIBILIDAD para P1116 ===")
cur.execute("SELECT id, HEX(dia) AS dia_hex, dia, hora_inicio, hora_fin FROM profesor_disponibilidad WHERE profesor_id='P1116' ORDER BY id")
for row in cur.fetchall():
    print(f"  id={row['id']} dia_hex={row['dia_hex']!r} dia={row['dia']!r} ini={row['hora_inicio']} fin={row['hora_fin']}")

conn.close()
