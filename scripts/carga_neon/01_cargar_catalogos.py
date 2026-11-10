#!/usr/bin/env python3
"""
01_cargar_catalogos.py
======================
Carga (y mantiene) los VALORES de los catálogos: las etapas, las provincias y las categorías de cada variable multivalor.
Se puede correr todas las veces que haga falta: es idempotente y NO rompe nada de lo ya cargado.

Uso:
    python 01_cargar_catalogos.py --dry-run     # muestra qué haría y deshace (no cambia nada)
    python 01_cargar_catalogos.py               # aplica

Cada categoría tiene dos textos:
  * valor        -> el nombre CORTO que se guarda y se usa en los análisis y dashboards.
  * descripcion  -> (opcional) el texto LARGO tal como lo ve el participante en el formulario / futura web,
                    con las aclaraciones entre paréntesis. Si no hace falta, se omite y la web muestra el valor.
  Formato: (id, 'valor corto')   o   (id, 'valor corto', 'texto largo del formulario')

Cómo se cambian los valores (acá, NO con ALTER TABLE: eso es solo para cambiar la estructura):
  * AGREGAR una categoría   -> sumar una línea nueva con un id que no exista (el siguiente número libre).
  * RENOMBRAR una categoría -> cambiar el texto y dejar el MISMO id. Todas las observaciones ya cargadas
                               siguen apuntando a ese id, así que pasan a mostrar el nombre nuevo solas.
                               (El CSV de observaciones tiene que usar el nombre nuevo para la próxima carga.)
  * NO reutilizar ni cambiar el id de una categoría que ya tiene observaciones: el id es el que las une.
  * Este script nunca borra. Si una categoría se saca del código, queda en la base (y avisa);
    borrarla es una decisión manual y la base no deja borrarla mientras haya observaciones que la usen.
  * UNIFICAR dos categorías en una no es renombrar: hay que reasignar las observaciones de una a la otra
    (UPDATE en la tabla intermedia) y recién después borrar la que sobra. Se hace aparte, a mano.

Orden de ejecución: 01_cargar_catalogos -> 02_cargar_sitios -> 03_cargar_observaciones
"""
import argparse
import sys
from psycopg2.extras import execute_values
from scripts.carga_neon.helpers import cerrar, conectar

# VALORES DE LOS CATÁLOGOS  formato: (id, 'texto')
ETAPAS = [
    (1, 'Siembra y emergencia'),
    (2, 'Trasplante a maceta'),
    (3, 'Trasplante a suelo'),
    (4, 'Labores'),
    (5, 'Crecimiento y desarrollo'),
    (6, 'Labores durante fructificación'),
    (7, 'Cosecha y poscosecha'),
    (8, 'Degustación'),
]

# 23 provincias + CABA. Tener en cuenta que los ids actuales del 1 a 12 corresponden a las provincias 
# de las cuales hay participantes en estas 4 campañas trabajadas (no se deben cambiar), el resto se agregan para ya tenerlas.
# Las ciudades solas al cargar los sitios (02).
PROVINCIAS = [
    (1, 'Buenos Aires'), (2, 'CABA'), (3, 'Chubut'), (4, 'Córdoba'), (5, 'Entre Ríos'), (6, 'Mendoza'),
    (7, 'Misiones'), (8, 'Neuquén'), (9, 'Río Negro'), (10, 'San Luis'), (11, 'Santa Fe'), (12, 'Tucumán'),
    (13, 'Catamarca'), (14, 'Chaco'), (15, 'Corrientes'), (16, 'Formosa'), (17, 'Jujuy'), (18, 'La Pampa'),
    (19, 'La Rioja'), (20, 'Salta'), (21, 'San Juan'), (22, 'Santa Cruz'), (23, 'Santiago del Estero'),
    (24, 'Tierra del Fuego'),
]

# tablas cuyo catálogo es solo (id, nombre), sin descripción
PARES = ('etapas', 'provincias')

# tabla de catálogo -> (columna id, [(id, valor, descripción), ...])
CATALOGOS = {
    'cat_sustrato': ('sustrato_id', [
        (1, 'Suelo / tierra sola', 'Suelo / tierra sola (del lugar o comprada, por ejemplo tierra negra)'),
        (2, 'Suelo / tierra con materia orgánica y enmiendas', 'Suelo / tierra con materia orgánica y enmiendas (procesadas y sin procesar)'),
        (3, 'Suelo / tierra con minerales y aireantes', 'Suelo / tierra con minerales y aireantes (perlita, vermiculita, etc)'),
        (4, 'Sustrato comercial'),
    ]),
    'cat_cultivo_asociado': ('cultivo_asociado_id', [
        (1, 'No hubo'),
        (2, 'Frutas y hortalizas', 'Frutas y hortalizas (zapallo, lechuga, etc.)'),
        (3, 'Aromáticas y medicinales', 'Aromáticas y medicinales (albahaca, romero, etc.)'),
        (4, 'Flores y ornamentales'),
        (5, 'Otro'),
    ]),
    'cat_fertilizacion': ('fertilizacion_id', [
        (1, 'No utilicé'),
        (2, 'Compost, lombricompuesto, humus o bokashi'),
        (3, 'Abonos líquidos o biopreparados'),
        (4, 'Fertilizantes químicos o comerciales'),
        (5, 'Abono verde'),
        (6, 'Otra'),
        (7, "Combiné más de una opción")
    ]),
    'cat_control_plagas': ('control_plagas_id', [
        (1, 'No realicé control'),
        (2, 'Retiro manual'),
        (3, 'Trampas o barreras físicas'),
        (4, 'Biopreparados', 'Biopreparados (extractos, jabón potásico, etc.)'),
        (5, 'Control biológico'),
        (6, 'Producto comercial de síntesis'),
        (7, 'Otro'),
        (8, "Combiné más de una opción")
    ]),
    'cat_causa_desuniformidad': ('causa_desuniformidad_id', [
        (1, 'No hubo desuniformidad'),
        (2, 'Diferencias en el manejo', 'Diferencias en el manejo (riego, labores, nutrición)'),
        (3, 'Diferencias en el ambiente', 'Diferencias en el terreno, el contenedor o la luz'),
        (4, 'Hubo desuniformidad, aunque todas tuvieron las mismas condiciones'),
        (5, 'Pocas plantas para evaluarlo (1 o 2)'),
    ]),
    'cat_sanidad_observada': ('sanidad_observada_id', [
        (1, 'No se observó ningún problema'),
        (2, 'Bichitos chicos', 'Bichitos chicos (pulgones, arañuelas, chinches, etc.)'),
        (3, 'Bichos grandes', 'Bichos grandes (orugas, babosas, langostas, etc.)'),
        (4, 'Manchas en hojas o tallos'),
        (5, 'Hojas amarillas, enruladas o deformadas'),
        (6, 'Hojas con caminitos, agujeros o mordidas'),
        (7, 'Plantas marchitas aunque tengan agua'),
        (8, 'Polvillo o manchas blancas sobre las hojas'),
        (9, 'Frutos con manchas o podridos', 'Frutos con manchas, podridos o con la punta negra'),
        (10, 'Daños de vertebrados en frutos u hojas', 'Mordeduras de mamíferos o picoteos de aves en frutos u hojas')
    ]),
    'cat_causa_muerte_plantas': ('causa_muerte_plantas_id', [
        (1, 'No murieron plantas'),
        (2, 'Virus rugoso'),
        (3, 'Otras enfermedades'),
        (4, 'Plagas'),
        (5, 'Falta de agua o calor extremo'),
        (6, 'Helada'),
        (7, 'Problemas en el trasplante'),
        (8, 'No sé')
    ]),
    'cat_control_malezas': ('control_malezas_id', [
        (1, 'No realicé control'),
        (2, 'Retiro manual o con herramientas'),
        (3, 'Herbicida químico o comercial'),
        (4, 'Cobertura u otro método físico'),   
        (5, 'Otro'),
    ]),
    'cat_cobertura_suelo': ('cobertura_suelo_id', [
        (1, 'Sin cobertura'),
        (2, 'Cobertura vegetal', 'Cobertura vegetal (hojas secas o restos vegetales)'),
        (3, 'Cobertura plástica, cartón u otra similar'),
        (4, 'Otra'),
    ]),
}

# Doble seguridad: se sacan los espacios sobrantes de los textos, el CSV de observaciones se lee con strip()
def _normalizar(filas):
    """(id, valor) o (id, valor, descripcion) -> (id, valor, descripcion o None), sin espacios sobrantes."""
    out = []
    for f in filas:
        desc = f[2].strip() if len(f) > 2 and f[2] and f[2].strip() else None
        out.append((f[0], f[1].strip(), desc))
    return out

ETAPAS = [(i, v.strip()) for i, v in ETAPAS]
PROVINCIAS = [(i, v.strip()) for i, v in PROVINCIAS]
CATALOGOS = {t: (c, _normalizar(filas)) for t, (c, filas) in CATALOGOS.items()}


# ----------------------------------------------------------------------------
# Validaciones (seguridad e integridad) y carga
def validar_codigo():
    """Revisa que el código no tenga ids ni textos repetidos antes de tocar la base."""
    problemas = []
    todos = {'etapas': [(i, v, None) for i, v in ETAPAS], 'provincias': [(i, v, None) for i, v in PROVINCIAS]}
    todos.update({t: filas for t, (_, filas) in CATALOGOS.items()})
    for tabla, filas in todos.items():
        ids = [i for i, _, _ in filas]
        vals = [v for _, v, _ in filas]
        descs = [d for _, _, d in filas if d]
        if len(ids) != len(set(ids)):
            problemas.append(f"{tabla}: hay ids repetidos")
        if len(vals) != len(set(vals)):
            problemas.append(f"{tabla}: hay valores repetidos")
        if any(not v for v in vals):
            problemas.append(f"{tabla}: hay valores vacíos")
        if len(descs) != len(set(descs)):
            problemas.append(f"{tabla}: hay descripciones repetidas")
        for i, v, d in filas:
            if d and d != v and d in vals:
                problemas.append(f"{tabla}: la descripción del id {i} coincide con el valor de otra categoría")
    if problemas:
        sys.exit('ERROR en los valores definidos en este archivo (no se tocó la base):\n  - ' + '\n  - '.join(problemas))


def sincronizar(cur, tabla, col_id, filas):
    """Inserta lo nuevo, actualiza lo que cambió (mismo id) y avisa de lo que sobra en la base."""
    es_etapa = tabla in PARES   # sin descripción
    if es_etapa:
        filas = [(i, v, None) for i, v in filas]
        cur.execute(f'SELECT "{col_id}", nombre, NULL FROM "{tabla}"')
    else:
        cur.execute(f'SELECT "{col_id}", valor, descripcion FROM "{tabla}"')
    en_base = {i: (v, d) for i, v, d in cur.fetchall()}
    nuevos = [f for f in filas if f[0] not in en_base]
    renombrados = [(i, en_base[i][0], v) for i, v, _ in filas if i in en_base and en_base[i][0] != v]
    desc_cambiadas = [i for i, _, d in filas if i in en_base and en_base[i][1] != d] if not es_etapa else []
    cambiados = {i for i, _, _ in renombrados} | set(desc_cambiadas)
    sin_cambios = len(filas) - len(nuevos) - len(cambiados)
    ids_codigo = {i for i, _, _ in filas}
    sobran = sorted((i, v) for i, (v, _) in en_base.items() if i not in ids_codigo)

    if filas:
        if es_etapa:
            execute_values(cur, f'INSERT INTO "{tabla}" ("{col_id}", nombre) VALUES %s ON CONFLICT ("{col_id}") '
                                'DO UPDATE SET nombre = EXCLUDED.nombre', [(i, v) for i, v, _ in filas])
        else:
            execute_values(cur, f'INSERT INTO "{tabla}" ("{col_id}", valor, descripcion) VALUES %s '
                                f'ON CONFLICT ("{col_id}") DO UPDATE SET valor = EXCLUDED.valor, '
                                f'descripcion = EXCLUDED.descripcion', filas)
        # los ids se pusieron a mano: avanzar la secuencia para que futuros inserts automáticos no choquen
        cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (f'public.{tabla}', col_id))
        seq = cur.fetchone()[0]
        if seq:
            cur.execute(f'SELECT setval(%s, (SELECT MAX("{col_id}") FROM "{tabla}"))', (seq,))

    extra = '' if es_etapa else f" | descripciones nuevas/cambiadas: {len(desc_cambiadas) + sum(1 for f in nuevos if f[2]):2d}"
    print(f"  {tabla:28s} nuevos: {len(nuevos):2d} | renombrados: {len(renombrados):2d} | sin cambios: {sin_cambios:2d}{extra}")
    for i, antes, ahora in renombrados:
        print(f"      id {i}: '{antes}'  ->  '{ahora}'")
    for i, v in sobran:
        print(f"      AVISO: id {i} '{v}' está en la base pero ya no figura en este archivo (no se borra)")
    return len(nuevos), len(renombrados)


def main():
    ap = argparse.ArgumentParser(description='Carga/actualiza los valores de los catálogos (idempotente).')
    ap.add_argument('--dry-run', action='store_true', help='hace todo y deshace al final: no cambia la base')
    args = ap.parse_args()

    validar_codigo()
    conn = conectar()
    try:
        cur = conn.cursor()
        print('Catálogos:')
        total_n = total_r = 0
        for tabla, col_id, filas in [('etapas', 'etapa_id', ETAPAS), ('provincias', 'provincia_id', PROVINCIAS)] + [(t, c, f) for t, (c, f) in CATALOGOS.items()]:
            n, r = sincronizar(cur, tabla, col_id, filas)
            total_n += n
            total_r += r
        cerrar(conn, args.dry_run, f'{total_n} valores nuevos, {total_r} renombrados')
    except Exception as e:
        conn.rollback()
        sys.exit(f"ERROR de base de datos (no se cambió nada): {e}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
