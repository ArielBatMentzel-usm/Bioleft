# Bioleft · Tablero de ensayos agronómicos

Tablero en Streamlit que lee los ensayos desde la base en Neon (PostgreSQL) y muestra
panorama general, variedades, prácticas de manejo, degustación y calidad de datos.

El app lee **una sola vista**, `v_ensayos_ancho` (una fila por ensayo), definida en `vistas.sql` y cargada en Neon.

## Requisitos

- Python 3.10 o superior
- Acceso a la base en Neon 

## 1. Configurar la conexión

Creá un archivo `.env` en la raíz del proyecto (no se sube a GitHub, ya está en `.gitignore`):

```
DATABASE_URL=postgresql://usuario:contraseña@host/basededatos?sslmode=require
```

## 2. (Opcional) Crear un entorno virtual

Recomendado para no mezclar librerías con otros proyectos.

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Instalar las dependencias

```bash
pip install -r requirements.txt
```

## 4. Correr el tablero

```bash
streamlit run app.py
```

Se abre en el navegador en http://localhost:8501.

## Notas


## Archivos

| Archivo | Para qué sirve |
|---|---|
| `app.py` | El tablero |
| `requirements.txt` | Dependencias de Python |
| `vistas.sql` | Definición de la vista `v_ensayos_ancho` |
| `.gitignore` | Evita subir `.env` y archivos temporales |





*Aclaración importante sobre el procesador de comentarios*: se revisó, iteró y aseguró el correcto funcionamiento y la consistencia de los resultados del archivo `comentarios/procesar_comentarios.py` sobre las reglas definidas. Pero no se indagó en como se procesaban estos comentarios, la revisión humana fue más por el lado de garantizar la integridad y coherencia de los resultados y las observaciones agregadas.