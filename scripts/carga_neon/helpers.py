"""
bioleft_comun.py
================
Código compartido por los scripts de carga (conexión a Neon).

Requisitos:   pip install pandas psycopg2-binary python-dotenv
Conexión:     DATABASE_URL = la cadena que te da Neon. NUNCA va en el código ni en git. Dos formas:
              a) Archivo .env en la raíz del repo (con .env dentro de .gitignore):
                     DATABASE_URL=postgresql://usuario:clave@host/db?sslmode=require
                 Los scripts lo leen solos (necesita python-dotenv).
              b) Variable de entorno del sistema:
                     Windows (PowerShell):  $env:DATABASE_URL = "postgresql://..."
                     Mac/Linux:             export DATABASE_URL="postgresql://..."
              Si están las dos, manda la variable de entorno.
"""
import os
import sys

import psycopg2

try:   # opcional: lee DATABASE_URL de un archivo .env (buscándolo desde la carpeta actual hacia arriba)
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass


def conectar():
    url = os.environ.get('DATABASE_URL')
    if not url:
        sys.exit('ERROR: falta DATABASE_URL (cadena de conexión de Neon). Ponela en un archivo .env en la raíz del '
                 'repo (y .env en .gitignore) o como variable de entorno del sistema.')
    return psycopg2.connect(url)


def cerrar(conn, dry_run, mensaje_ok):
    """Confirma o deshace la transacción. En --dry-run siempre deshace."""
    if dry_run:
        conn.rollback()
        print(f"\nDRY-RUN: todo se ejecutó bien y se DESHIZO. La base no cambió. ({mensaje_ok})")
    else:
        conn.commit()
        print(f"\nOK: {mensaje_ok}")
