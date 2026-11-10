#!/usr/bin/env python3
"""
02_cargar_sitios.py
===================
Carga participantes (incluido genero), provincias, ciudades y sitios.
- sitios_ubicacion.csv: sitio_id, participante_id, provincia, localidad.
- participantes.csv: participante_id, genero.

Es idempotente: se puede correr todas las veces que haga falta.
  * las provincias vienen definidas en 01_cargar_catalogos.py (las 23 + CABA): si el CSV trae una que no existe
    (por ejemplo por un error de tipeo) el script se detiene y avisa, no crea provincias nuevas.
  * las ciudades se crean solas (id automático); las que ya existen no se duplican.
  * los participantes se insertan si no existen y su genero se actualiza desde participantes.csv.
  * un sitio que ya existe se actualiza (participante, provincia, ciudad) con lo que diga el CSV.
  * no borra nada: si un sitio está en la base pero no en el CSV, solo avisa.
  * provincia o localidad vacías quedan en NULL (sitio sin ubicación / con solo provincia).

Uso (ambos CSV tienen rutas por defecto dentro de data/processed/):
    python scripts/carga_neon/02_cargar_sitios.py --dry-run
    python scripts/carga_neon/02_cargar_sitios.py ruta/sitios_ubicacion.csv
    python scripts/carga_neon/02_cargar_sitios.py ruta/sitios_ubicacion.csv --csv-participantes ruta/participantes.csv

Orden de ejecución: 01_cargar_catalogos -> 02_cargar_sitios -> 03_cargar_observaciones
"""
import argparse
import difflib
import sys
from pathlib import Path

import pandas as pd
from psycopg2.extras import execute_values

from helpers import cerrar, conectar

COLUMNAS_SITIOS = ['sitio_id', 'participante_id', 'provincia', 'localidad']
COLUMNAS_PARTICIPANTES = ['participante_id', 'genero']

# Si no se pasa ruta, se busca en <raíz del repo>/data/processed/
CSV_POR_DEFECTO = (
    Path(__file__).resolve().parent.parent.parent
    / 'data' / 'processed' / 'sitios_ubicacion.csv'
)
CSV_PARTICIPANTES_POR_DEFECTO = (
    Path(__file__).resolve().parent.parent.parent
    / 'data' / 'processed' / 'participantes.csv'
)

def leer_csv_sitios(ruta):
    if not Path(ruta).is_file():
        sys.exit(f"ERROR: no se encontró el CSV de sitios en {ruta}\n       Pasa la ruta como argumento: python 02_cargar_sitios.py ruta/al/sitios_ubicacion.csv")
    df = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    faltan = set(COLUMNAS_SITIOS) - set(df.columns)
    if faltan:
        sys.exit(f"ERROR: al CSV le faltan columnas: {sorted(faltan)}")
    df = df[COLUMNAS_SITIOS].apply(lambda c: c.str.strip())
    problemas = []
    if df['sitio_id'].eq('').any() or df['participante_id'].eq('').any():
        problemas.append("hay filas sin sitio_id o sin participante_id")
    if df['sitio_id'].duplicated().any():
        problemas.append(f"sitio_id repetidos: {df.loc[df['sitio_id'].duplicated(), 'sitio_id'].tolist()}")
    sin_prov = df[df['provincia'].eq('') & df['localidad'].ne('')]
    if len(sin_prov):
        problemas.append(f"localidad sin provincia (no se puede ubicar la ciudad): {sin_prov['sitio_id'].tolist()}")
    if problemas:
        sys.exit('ERROR en el CSV (no se tocó la base):\n  - ' + '\n  - '.join(problemas))
    return df


def leer_csv_participantes(ruta):
    """Lee participante_id y genero desde participantes.csv."""
    if not Path(ruta).is_file():
        sys.exit(f"ERROR: no se encontró el CSV de participantes en {ruta}")

    df = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    faltan = set(COLUMNAS_PARTICIPANTES) - set(df.columns)
    if faltan:
        sys.exit(f"ERROR: al CSV de participantes le faltan columnas: {sorted(faltan)}")

    df = df[COLUMNAS_PARTICIPANTES].apply(lambda c: c.str.strip())
    problemas = []
    if df['participante_id'].eq('').any():
        problemas.append("hay filas sin participante_id")
    if df['participante_id'].duplicated().any():
        repetidos = df.loc[df['participante_id'].duplicated(keep=False), 'participante_id'].unique().tolist()
        problemas.append(f"participante_id repetidos: {repetidos}")

    if problemas:
        sys.exit('ERROR en el CSV de participantes (no se tocó la base):\n  - ' + '\n  - '.join(problemas))

    df['genero'] = df['genero'].replace('', None)
    return df

# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description='Carga participantes, provincias, ciudades y sitios.')
    ap.add_argument('csv', nargs='?', default=str(CSV_POR_DEFECTO),
                    help=f'ruta del CSV de sitios (por defecto: {CSV_POR_DEFECTO})')
    ap.add_argument('--csv-participantes', default=str(CSV_PARTICIPANTES_POR_DEFECTO),
                    help=f'ruta del CSV de participantes (por defecto: {CSV_PARTICIPANTES_POR_DEFECTO})')
    ap.add_argument('--dry-run', action='store_true', help='hace todo y deshace al final: no cambia la base')
    args = ap.parse_args()

    df_sitios = leer_csv_sitios(args.csv)
    df_participantes = leer_csv_participantes(args.csv_participantes)
    conn = conectar()
    try:
        cur = conn.cursor()

        # participantes: primero asegura que existan los IDs asociados a sitios.
        execute_values(cur, "INSERT INTO participantes (participante_id) VALUES %s ON CONFLICT (participante_id) DO NOTHING",
                       [(p,) for p in sorted(df_sitios['participante_id'].unique())])

        # Género: inserta o actualiza el dato desde participantes.csv.
        # Si genero está vacío en el CSV, se guarda NULL (el CSV es la fuente de verdad).
        filas_participantes = list(df_participantes.itertuples(index=False, name=None))
        if filas_participantes:
            execute_values(
                cur,
                "INSERT INTO participantes (participante_id, genero) VALUES %s "
                "ON CONFLICT (participante_id) DO UPDATE SET genero = EXCLUDED.genero",
                filas_participantes
            )

        # provincias: están definidas de antemano en 01_cargar_catalogos.py (acá solo se buscan por nombre)
        provincias = sorted(p for p in df_sitios['provincia'].unique() if p)
        cur.execute("SELECT nombre, provincia_id FROM provincias")
        prov_id = dict(cur.fetchall())
        desconocidas = [p for p in provincias if p not in prov_id]
        if desconocidas:
            msgs = []
            for p in desconocidas:
                cerca = difflib.get_close_matches(p, prov_id, n=1)
                msgs.append(f"'{p}'" + (f" (¿será '{cerca[0]}'?)" if cerca else ''))
            sys.exit("ERROR: provincias del CSV que no existen en la base: " + ', '.join(msgs) +
                     "\n       Corregir el CSV, o agregarlas en PROVINCIAS de 01_cargar_catalogos.py y correrlo. No se cambió nada.")

        # ciudades (únicas por nombre + provincia)
        ciudades = sorted({(r.localidad, prov_id[r.provincia]) for r in df_sitios.itertuples() if r.localidad})
        if ciudades:
            execute_values(cur, "INSERT INTO ciudades (nombre, provincia_id) VALUES %s "
                                "ON CONFLICT (nombre, provincia_id) DO NOTHING", ciudades)
        cur.execute("SELECT nombre, provincia_id, ciudad_id FROM ciudades")
        ciu_id = {(n, p): c for n, p, c in cur.fetchall()}

        # sitios
        filas = []
        for r in df_sitios.itertuples():
            pid = prov_id[r.provincia] if r.provincia else None
            cid = ciu_id[(r.localidad, pid)] if r.localidad else None
            filas.append((r.sitio_id, r.participante_id, pid, cid))
        execute_values(cur, "INSERT INTO sitios (sitio_id, participante_id, provincia_id, ciudad_id) VALUES %s "
                            "ON CONFLICT (sitio_id) DO UPDATE SET participante_id = EXCLUDED.participante_id, "
                            "provincia_id = EXCLUDED.provincia_id, ciudad_id = EXCLUDED.ciudad_id", filas)

        cur.execute("SELECT sitio_id FROM sitios WHERE NOT (sitio_id = ANY(%s))", (df_sitios['sitio_id'].tolist(),))
        for (s,) in cur.fetchall():
            print(f"AVISO: el sitio {s} está en la base pero no en el CSV (no se borra)")

        sin_ubic = int(df_sitios['provincia'].eq('').sum())
        print(f"Participantes en sitios: {df_sitios['participante_id'].nunique()} | participantes con datos de género en CSV: {len(df_participantes)} | provincias: {len(provincias)} | "
              f"ciudades: {len(ciudades)} | sitios: {len(df_sitios)} ({sin_ubic} sin ubicación)")
        cerrar(conn, args.dry_run, f'{len(df_sitios)} sitios y {len(df_participantes)} participantes cargados/actualizados')
    except Exception as e:
        conn.rollback()
        sys.exit(f"ERROR de base de datos (no se cambió nada): {e}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
