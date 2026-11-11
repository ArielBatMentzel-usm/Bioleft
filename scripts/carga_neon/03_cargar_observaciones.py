#!/usr/bin/env python3
"""
03_cargar_observaciones.py
==========================
Carga el dataset final en formato LARGO (observaciones_agronomicas_limpio.csv) a las tablas de Neon
(ensayos, una tabla por etapa, tablas intermedias de las variables multivalor y comentarios).

Antes hay que haber corrido (una vez, y de nuevo cada vez que cambien los valores / sitios):
    python -m scripts.carga_neon.01_cargar_catalogos
    python -m scripts.carga_neon.02_cargar_sitios

Uso (desde la raíz del proyecto; la ruta del CSV es opcional: por defecto lee <raíz del repo>/data/processed/observaciones_agronomicas_limpio.csv):  
    python -m scripts.carga_neon.03_cargar_observaciones --dry-run                              # prueba todo y deshace
    python -m scripts.carga_neon.03_cargar_observaciones                                        # carga de verdad
    python -m scripts.carga_neon.03_cargar_observaciones campana_nueva.csv --campanas 2026-2027 # solo esa campaña


    
Cómo funciona (modo "reemplazar por campaña"):
  * Para cada campaña que viene en el CSV: borra sus ensayos en la base (y, en cascada, sus etapas, valores
    multivalor y comentarios) y los vuelve a cargar. Correrlo dos veces deja la base igual (idempotente).
  * Las demás campañas no se tocan. degustacion_comparativa tampoco (no sale de este CSV).
  * Todo ocurre en UNA transacción: si algo falla, no queda nada a medias.
  * Cada variable simple se busca por nombre entre las columnas de la tabla de su etapa. Una variable del CSV
    sin columna en la base NO se carga y queda anotada en la conciliación (con aviso).
  * Los valores multivalor se traducen a id con los catálogos de la base (sirve tanto el valor corto como la
    descripción larga del formulario). Si aparece un texto que no está en el
    catálogo, el script se detiene y te dice cuál es (agregarlo en 01_cargar_catalogos.py y correrlo).
  * La columna `nota` del CSV no se carga (la base no guarda notas).
  * La columna `sub_ensayo` del CSV tampoco se guarda: solo separa ensayos que repiten campaña, sitio y variedad,
    y cada uno se carga como un ensayo distinto (con su propio ensayo_id).
  * Al final muestra una CONCILIACIÓN: cada fila del CSV termina en un lugar (o en "no cargadas", con motivo).
"""
import argparse
import sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd
from psycopg2.extras import execute_values

from scripts.carga_neon.helpers import cerrar, conectar

# Configuración del diseño
# Si no se pasa ruta, se busca en <raíz del repo>/data/processed/ 
CSV_POR_DEFECTO = (
    Path(__file__).resolve().parent.parent.parent
    / 'data' / 'processed' / 'observaciones_agronomicas_limpio.csv'
)

COLUMNAS_CSV = ['campaña', 'id_sitio', 'sub_ensayo', 'variedad_id', 'etapa', 'variable', 'valor']
COLUMNAS_OPCIONALES = ['anio_multiplicacion', 'lote_semillas']

# etapa del CSV -> tabla de esa etapa en la base
ETAPA_A_TABLA = {
    'Siembra y emergencia': 'siembra',
    'Trasplante a maceta': 'trasplante_maceta',
    'Trasplante a suelo': 'trasplante_suelo',
    'Labores': 'labores',
    'Crecimiento y desarrollo': 'crecimiento',
    'Labores durante fructificación': 'labores_fructificacion',
    'Cosecha y poscosecha': 'cosecha_poscosecha',
    'Degustación': 'degustacion',
}

# variables que en el CSV tienen otro nombre que la columna de la base: (etapa, variable del CSV) -> columna
RENOMBRES = {
    ('Trasplante a suelo', 'cantidad_plantas_trasplantadas_parcela'): 'cantidad_plantines_trasplantados',
    ('Trasplante a suelo', 'cantidad_plantas_implantadas'): 'cantidad_plantines_implantados',
    ('Cosecha y poscosecha', 'cantidad_frutos_cosechados'): 'total_frutos_cosechados',
}

# variable multivalor del CSV -> (tabla intermedia, tabla de catálogo, columna id del catálogo, tabla de su etapa)
MULTIVALOR = {
    'sustrato':                ('sustrato', 'cat_sustrato', 'sustrato_id', 'trasplante_maceta'),
    'cultivo_asociado_maceta': ('cultivo_asociado_maceta', 'cat_cultivo_asociado', 'cultivo_asociado_id', 'trasplante_maceta'),
    'cultivo_asociado_suelo':  ('cultivo_asociado_suelo', 'cat_cultivo_asociado', 'cultivo_asociado_id', 'trasplante_suelo'),
    'fertilizacion':           ('fertilizacion', 'cat_fertilizacion', 'fertilizacion_id', 'labores'),
    'control_plagas':          ('control_plagas', 'cat_control_plagas', 'control_plagas_id', 'labores'),
    'control_malezas':         ('control_malezas', 'cat_control_malezas', 'control_malezas_id', 'labores'),
    'cobertura_suelo':         ('cobertura_suelo', 'cat_cobertura_suelo', 'cobertura_suelo_id', 'trasplante_suelo'),
    'causa_desuniformidad':    ('causa_desuniformidad', 'cat_causa_desuniformidad', 'causa_desuniformidad_id', 'crecimiento'),
    'sanidad_observada':       ('sanidad_observada', 'cat_sanidad_observada', 'sanidad_observada_id', 'crecimiento'),
    'causa_muerte_plantas':    ('causa_muerte_plantas', 'cat_causa_muerte_plantas', 'causa_muerte_plantas_id', 'crecimiento'),
}
COMENTARIOS = 'comentarios_generales'

ATRIBUTOS_DEGUSTACION = ['dulce', 'acido', 'jugoso', 'persistente', 'olor_tomate_maduro', 'olor_tomate_verde',
                         'mucha_pulpa', 'poca_pulpa', 'pulpa_dura', 'pulpa_blanda', 'mucha_semilla', 'poca_semilla',
                         'aguachento', 'pastoso', 'piel_dura']
GUSTO_GENERAL = 'gusto_general'



# Lectura del CSV
def leer_csv(ruta, campanas=None):
    if not Path(ruta).is_file():
        sys.exit(f"ERROR: no se encontró el CSV de observaciones en {ruta}\n       Pasa la ruta como argumento: python 03_cargar_observaciones.py ruta/al/observaciones_agronomicas_limpio.csv")
    df = pd.read_csv(ruta, dtype=str, keep_default_na=False)      # vacío = '' 
    faltan = set(COLUMNAS_CSV) - set(df.columns)
    if faltan:
        sys.exit(f"ERROR: al CSV le faltan columnas: {sorted(faltan)}")
    cols = COLUMNAS_CSV + [c for c in COLUMNAS_OPCIONALES if c in df.columns]
    df = df[cols].apply(lambda c: c.str.strip())
    for c in ('sub_ensayo', 'anio_multiplicacion'):
        df[c] = df[c].str.replace(r'\.0$', '', regex=True)          # '2.0' -> '2'
    vacias = df[(df[COLUMNAS_CSV] == '').any(axis=1)]
    if len(vacias):
        sys.exit(f"ERROR: {len(vacias)} filas con clave, etapa, variable o valor vacío (primeras filas del CSV: "
                 f"{(vacias.index[:5] + 2).tolist()}). Corregirlas o sacarlas antes de cargar.")
    if campanas:
        df = df[df['campaña'].isin(campanas)]
        if df.empty:
            sys.exit(f"ERROR: el CSV no tiene filas de las campañas {campanas}")
    return df.reset_index(drop=True)



# Lo que dice la base: columnas por tabla, catálogos y etapas
def leer_esquema(cur):
    columnas = {}
    for tabla in ETAPA_A_TABLA.values():
        cur.execute("SELECT column_name, data_type, numeric_precision, numeric_scale FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (tabla,))
        columnas[tabla] = {c: (t, p, s) for c, t, p, s in cur.fetchall() if c != 'ensayo_id'}
        if not columnas[tabla]:
            sys.exit(f"ERROR: no existe la tabla {tabla}. Correr primero los archivos SQL de la carpeta bioleft_sql.")
    catalogos = {}
    for _, cat, col_id, _ in MULTIVALOR.values():
        if cat not in catalogos:
            cur.execute(f'SELECT valor, descripcion, "{col_id}" FROM "{cat}"')
            catalogos[cat] = {}
            for valor, descripcion, vid in cur.fetchall():      # el CSV puede traer el valor corto o el texto largo
                catalogos[cat][valor] = vid
                if descripcion:
                    catalogos[cat][descripcion] = vid
    cur.execute("SELECT nombre, etapa_id FROM etapas")
    return columnas, catalogos, dict(cur.fetchall())



# Conversión de tipos
def convertir(valor, info, ctx, errores):
    tipo, prec, escala = info
    try:
        if tipo == 'boolean':
            return {'Sí': True, 'No': False}[valor]
        if tipo in ('integer', 'smallint', 'bigint'):
            f = float(valor)
            if f != int(f):
                raise ValueError('no es entero')
            return int(f)
        if tipo == 'numeric':
            d = Decimal(valor)
            if prec is not None and abs(d) >= Decimal(10) ** (prec - escala):
                raise OverflowError('fuera de rango')
            return d
        if tipo == 'date':
            return date.fromisoformat(valor)
        return valor
    except (ValueError, KeyError, InvalidOperation, OverflowError) as e:
        errores.append(f"{ctx}: '{valor}' no se puede convertir a {tipo} ({e.__class__.__name__})")
        return None



# Armado del plan (todavía sin tocar la base)
def armar_plan(df, columnas, catalogos, etapa_id):
    errores = []
    cuenta = Counter()                       # conciliación: a dónde fue cada fila
    sin_columna = Counter()                  # (etapa, variable) del CSV sin columna en la base
    faltan_en_catalogo = Counter()           # (catálogo, texto) que no existe
    etapas_raras = set()
    filas_etapa = defaultdict(dict)          # tabla -> clave -> {columna: valor}
    crudo = {}                               # (tabla, clave, columna) -> valor del CSV (para detectar repetidos distintos)
    repetidos_distintos = []
    multi = defaultdict(set)                 # tabla intermedia -> {(clave, id)}
    comentarios, comentarios_vistos = [], set()

    for camp, sitio, sub, var_ed, etapa, variable, valor in zip(df['campaña'], df['id_sitio'], df['sub_ensayo'],
                                                                   df['variedad_id'], df['etapa'], df['variable'], df['valor']):
        if not sub.isdigit():
            errores.append(f"sub_ensayo '{sub}' no es un número entero (sitio {sitio})")
            continue
        clave = (camp, sitio, var_ed, int(sub))

        if variable == COMENTARIOS:                                            # --- comentarios
            if etapa not in etapa_id:
                etapas_raras.add(etapa)
                continue
            k = (clave, etapa, valor)
            if k in comentarios_vistos:
                cuenta['no cargadas: comentario idéntico repetido en el mismo ensayo y etapa'] += 1
            else:
                comentarios_vistos.add(k)
                comentarios.append((clave, etapa_id[etapa], valor))
                cuenta['comentarios'] += 1
            continue

        if variable in MULTIVALOR:                                             # --- multivalor
            inter, cat, _, tabla_etapa = MULTIVALOR[variable]
            vid = catalogos[cat].get(valor)
            if vid is None:
                faltan_en_catalogo[(cat, valor)] += 1
                continue
            if (clave, vid) in multi[inter]:
                cuenta['no cargadas: multivalor repetido (mismo ensayo, variable y valor)'] += 1
                continue
            multi[inter].add((clave, vid))
            filas_etapa[tabla_etapa].setdefault(clave, {})      # la FK exige que exista la fila de la etapa
            cuenta['multivalor (tablas intermedias)'] += 1
            continue

        tabla = ETAPA_A_TABLA.get(etapa)
        if tabla is None:
            etapas_raras.add(etapa)
            continue

        if tabla == 'degustacion' and (variable in ATRIBUTOS_DEGUSTACION or variable == GUSTO_GENERAL):   # --- degustación
            cols = columnas['degustacion']
            if variable == GUSTO_GENERAL:
                col, val = GUSTO_GENERAL, convertir(valor, cols[GUSTO_GENERAL], 'degustacion.gusto_general', errores)
            elif valor in ('Sí', 'No'):
                col, val = f'{variable}_marcado', valor == 'Sí'
            else:
                try:
                    n = float(valor)
                except ValueError:
                    errores.append(f"degustacion.{variable}: valor no reconocido '{valor}'")
                    continue
                if n != int(n):
                    errores.append(f"degustacion.{variable}: intensidad no entera '{valor}'")
                    continue
                col, val = f'{variable}_intensidad', int(n)
            if col not in cols:
                errores.append(f"degustacion: la base no tiene la columna {col}")
                continue
            reg = filas_etapa['degustacion'].setdefault(clave, {})
            if col in reg:
                cuenta['no cargadas: degustación repetida (mismo ensayo y atributo)'] += 1
                continue
            reg[col] = val
            cuenta['degustación'] += 1
            continue

        col = RENOMBRES.get((etapa, variable), variable)                       # --- variables simples
        if col not in columnas[tabla]:
            sin_columna[(etapa, variable)] += 1
            cuenta[f'no cargadas: sin columna en la base ({etapa} / {variable})'] += 1
            continue
        reg = filas_etapa[tabla].setdefault(clave, {})
        if col in reg:
            cuenta['no cargadas: variable simple repetida en el mismo ensayo (queda la primera)'] += 1
            if crudo[(tabla, clave, col)] != valor:
                repetidos_distintos.append((tabla, col, clave, crudo[(tabla, clave, col)], valor))
            continue
        reg[col] = convertir(valor, columnas[tabla][col], f'{tabla}.{col}', errores)
        crudo[(tabla, clave, col)] = valor
        cuenta['etapas (variables simples)'] += 1

    for (cat, valor), n in sorted(faltan_en_catalogo.items()):
        errores.append(f"{cat}: el valor '{valor}' ({n} filas) no está en el catálogo -> agregarlo en 01_cargar_catalogos.py y correrlo")
    for e in sorted(etapas_raras):
        errores.append(f"etapa '{e}' no reconocida (no está en la base ni en ETAPA_A_TABLA)")

    # atributos del ensayo (anio_multiplicacion, lote_semillas): un solo valor por ensayo
    ensayos = {}
    extras = [c for c in COLUMNAS_OPCIONALES if c in df.columns]
    for fila in df.to_dict('records'):
        if not fila['sub_ensayo'].isdigit():
            continue
        clave = (fila['campaña'], fila['id_sitio'], fila['variedad_id'], int(fila['sub_ensayo']))
        attrs = ensayos.setdefault(clave, {c: set() for c in extras})
        for c in extras:
            if fila[c]:
                attrs[c].add(fila[c])
    for clave, attrs in ensayos.items():
        for c, vals in attrs.items():
            if len(vals) > 1:
                errores.append(f"ensayo {clave}: {c} con más de un valor distinto {sorted(vals)}")
    return dict(ensayos=ensayos, filas_etapa=filas_etapa, multi=multi, comentarios=comentarios, cuenta=cuenta,
                errores=errores, sin_columna=sin_columna, repetidos_distintos=repetidos_distintos)


def conciliacion(df, plan):
    print('\n=== CONCILIACIÓN (a dónde fue cada fila del CSV) ===')
    total = 0
    for k, n in sorted(plan['cuenta'].items(), key=lambda kv: (kv[0].startswith('no cargadas'), kv[0])):
        print(f"  {n:6d}  {k}")
        total += n
    ok = total == len(df)
    print(f"  {total:6d}  TOTAL  {'== filas del CSV (' + str(len(df)) + ') OK' if ok else '!= filas del CSV (' + str(len(df)) + ') REVISAR'}")
    if plan['sin_columna']:
        print('\n  AVISO: estas variables del CSV NO se cargaron porque la base no tiene una columna con ese nombre:')
        for (etapa, variable), n in plan['sin_columna'].items():
            print(f"         - {variable} ({etapa}): {n} filas")
    if plan['repetidos_distintos']:
        print(f"\n  AVISO: {len(plan['repetidos_distintos'])} variables simples repetidas en un mismo ensayo con valores DISTINTOS "
              f"(se cargó la primera). Primeras:")
        for tabla, col, clave, a, b in plan['repetidos_distintos'][:5]:
            print(f"         - {tabla}.{col} {clave}: '{a}' vs '{b}'")
    return ok



# Carga
def cargar(cur, plan, campanas, columnas):
    resumen = {}
    cur.execute("DELETE FROM ensayos WHERE campana = ANY(%s)", (sorted(campanas),))
    resumen['ensayos reemplazados'] = cur.rowcount

    execute_values(cur, "INSERT INTO campanas (campana, anio_inicio, anio_fin) VALUES %s ON CONFLICT DO NOTHING",
                   [(c, int(c[:4]), int(c[5:])) for c in sorted(campanas)])
    variedades = sorted({clave[2] for clave in plan['ensayos']})
    execute_values(cur, "INSERT INTO variedades (variedad_id) VALUES %s ON CONFLICT DO NOTHING",
                   [(v,) for v in variedades])

    # ids reservados de antemano: así cada ensayo del CSV queda asociado a su id sin depender del orden de RETURNING
    # (la base no guarda sub_ensayo; en el CSV solo sirve para separar ensayos repetidos)
    claves = list(plan['ensayos'])
    cur.execute("SELECT nextval(pg_get_serial_sequence('ensayos', 'ensayo_id')) FROM generate_series(1, %s)", (len(claves),))
    ids = dict(zip(claves, [i for (i,) in cur.fetchall()]))
    filas = []
    for clave, attrs in plan['ensayos'].items():
        camp, sitio, var_ed, sub = clave
        anio = int(next(iter(attrs['anio_multiplicacion']))) if attrs.get('anio_multiplicacion') else None
        lote = next(iter(attrs['lote_semillas'])) if attrs.get('lote_semillas') else None
        filas.append((ids[clave], camp, sitio, var_ed, anio, lote))
    execute_values(cur, "INSERT INTO ensayos (ensayo_id, campana, sitio_id, variedad_id, anio_multiplicacion, "
                        "lote_semillas) VALUES %s", filas)
    resumen['ensayos'] = len(ids)

    for tabla, por_clave in plan['filas_etapa'].items():
        cols = list(columnas[tabla])
        filas = [(ids[clave],) + tuple(vals.get(c) for c in cols) for clave, vals in por_clave.items()]
        if filas:
            execute_values(cur, f'INSERT INTO "{tabla}" (ensayo_id, {", ".join(chr(34) + c + chr(34) for c in cols)}) VALUES %s', filas)
        resumen[tabla] = len(filas)

    for variable, (inter, _, col_id, _) in MULTIVALOR.items():
        filas = [(ids[clave], vid) for clave, vid in sorted(plan['multi'].get(inter, ()))]
        if filas:
            execute_values(cur, f'INSERT INTO "{inter}" (ensayo_id, "{col_id}") VALUES %s', filas)
        resumen[inter] = len(filas)

    # fecha NULL a propósito: la fecha real de los comentarios históricos no se conoce
    filas = [(ids[clave], etapa_id, None, texto) for clave, etapa_id, texto in plan['comentarios']]
    if filas:
        execute_values(cur, "INSERT INTO comentarios (ensayo_id, etapa_id, fecha, texto) VALUES %s", filas)
    resumen['comentarios'] = len(filas)
    return resumen


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description='Carga el CSV largo a las tablas de Neon.')
    ap.add_argument('csv', nargs='?', default=str(CSV_POR_DEFECTO),
                    help=f'ruta del CSV de observaciones (por defecto: {CSV_POR_DEFECTO})')
    ap.add_argument('--campanas', nargs='+', help='cargar solo estas campañas (ej: 2026-2027)')
    ap.add_argument('--dry-run', action='store_true', help='hace todo y deshace al final: no cambia la base')
    args = ap.parse_args()

    df = leer_csv(args.csv, args.campanas)
    campanas = sorted(df['campaña'].unique())
    print(f"CSV: {len(df)} filas | campañas: {campanas} | variables: {df['variable'].nunique()}")

    conn = conectar()
    try:
        cur = conn.cursor()
        columnas, catalogos, etapa_id = leer_esquema(cur)
        cur.execute("SELECT sitio_id FROM sitios WHERE sitio_id = ANY(%s)", (sorted(df['id_sitio'].unique()),))
        faltan = sorted(set(df['id_sitio']) - {s for (s,) in cur.fetchall()})
        if faltan:
            sys.exit(f"ERROR: sitios del CSV que no están en la base: {faltan}\n       Correr 02_cargar_sitios.py (y revisar sitios_ubicacion.csv).")

        plan = armar_plan(df, columnas, catalogos, etapa_id)
        if plan['errores']:
            print('\nERRORES DE DATOS (no se cargó nada):')
            for p in plan['errores'][:40]:
                print('  -', p)
            if len(plan['errores']) > 40:
                print(f"  ... y {len(plan['errores']) - 40} más")
            sys.exit(1)
        if not conciliacion(df, plan):
            sys.exit('ERROR: la conciliación no cierra; no se cargó nada.')

        resumen = cargar(cur, plan, campanas, columnas)
        print('\nFilas insertadas por tabla:')
        for k, n in resumen.items():
            print(f"  {n:6d}  {k}")
        cerrar(conn, args.dry_run, f"{resumen['ensayos']} ensayos de las campañas {campanas} "
                                   f"(reemplazó {resumen['ensayos reemplazados']} existentes)")
    except Exception as e:
        conn.rollback()
        sys.exit(f"ERROR de base de datos (no se cargó nada): {e}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
