# Bioleft: Automatización y Visualización de Datos Agronómicos Participativos

Este repositorio contiene la arquitectura de datos, scripts de limpieza/ETL, esquemas SQL relacionales y el tablero interactivo desarrollados para depurar, centralizar y explorar los ensayos agronómicos participativos de tomates criollos de **Bioleft**.

---

## 📁 Estructura del Repositorio

```text
Bioleft/
├── app/
│   └── dashboard.py                       # Tablero interactivo desarrollado en Streamlit
├── data/
│   ├── raw/                               # Datos de partida históricos (sin modificar)
│   ├── interim/                           # Tablas e iteraciones intermedias de limpieza
│   └── processed/                         # CSVs consolidados y depurados
├── Documentos/
│   ├── DER_Bioleft.png                    # Diagrama Entidad-Relación del esquema PostgreSQL
│   └── diccionario_variables_bioleft.xlsx # Diccionario extendido de variables agronómicas
├── postgresql/                            # Scripts SQL DDL para PostgreSQL (Neon)
│   ├── 01_catalogos_y_base.sql
│   ├── 02_sitios_ensayos_y_etapas.sql
│   ├── 03_multivalor.sql
│   ├── 04_comentarios_y_comparativa.sql
│   ├── crear_esquema_completo.sql         # Script unificado para crear las 37 tablas
│   └── vista_ancha.sql                    # Definición de la vista v_ensayos_ancho para visualizaciones
├── scripts/
│   ├── carga_neon/                        # Pipeline ETL para insertar datos en la base a partir del csv en formato largo
│   │   ├── 01_cargar_catalogos.py
│   │   ├── 02_cargar_sitios.py
│   │   ├── 03_cargar_observaciones.py
│   │   └── helpers.py
│   └── tratamiento_comentarios/           # Procesador de texto libre por reglas
│       ├── decisiones_comentarios.csv
│       ├── pendientes_comentarios.csv
│       ├── procesar_comentarios.py
│       ├── reglas_comentarios.csv
│       └── test_procesar_comentarios.py
├── auditoria_y_preprocesamiento.ipynb     # Notebook principal de auditoría y depuración
├── requirements.txt                       # Dependencias de Python
└── README.md
```

---

## 🚀 Flujo de Ejecución

### 1. Preprocesamiento y Auditoría
El análisis exploratorio de calidad y la depuración del corpus de las 4 campañas se ejecutan en el cuaderno:
```bash
jupyter notebook auditoria_y_preprocesamiento.ipynb
```
Para procesar y extraer valores estructurados a partir de observaciones libres, se utiliza el módulo en `scripts/tratamiento_comentarios/procesar_comentarios.py`.
*Aclaración sobre el procesador de comentarios*: se revisó, iteró y aseguró el correcto funcionamiento y la consistencia de los resultados del procesador sobre las reglas definidas. Pero no se indagó en como se procesaban estos comentarios, la revisión humana fue más por el lado de garantizar la integridad y coherencia de los resultados y las observaciones agregadas. Esta limitado a las reglas definidas.

### 2. Base de Datos (PostgreSQL / Neon)
Para desplegar la estructura relacional en Neon:
1. Ejecutar `postgresql/crear_esquema_completo.sql` en el editor SQL.
2. Crear la vista optimizada ejecutando `postgresql/vista_ancha.sql`.

### 3. Pipeline de Carga (ETL)
Los scripts de carga consumen los CSVs de la carpeta `data/processed/` y admiten el parámetro `--dry-run` para pruebas sin persistencia:
```bash
python scripts/carga_neon/01_cargar_catalogos.py
python scripts/carga_neon/02_cargar_sitios.py
python scripts/carga_neon/03_cargar_observaciones.py
```

### 4. Tablero Interactivo (Streamlit)
Configurar la variable `DATABASE_URL` con la cadena de conexión a Neon y ejecutar (local):
```bash
streamlit run app/dashboard.py
```

---

## 🛠️ Instalación y Requisitos

1. Clonar el repositorio.
2. Crear y activar un entorno virtual:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # En macOS / Linux
   .venv\Scripts\activate     # En Windows
   ```
3. Instalar las dependencias necesarias:
   ```bash
   pip install -r requirements.txt
   ```