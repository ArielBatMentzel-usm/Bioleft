"""Bioleft · Tablero de ensayos agronómicos participativos (Streamlit).

Lee una vista ancha de Neon (v_ensayos_ancho, 1 fila por ensayo) usando DATABASE_URL
(.env en local, Secrets en Streamlit Cloud) y arma todos los tableros en pandas/plotly.

Es un tablero de consulta pública (no de control): tiene que entenderse solo.
Tres pestañas por audiencia:
  1. Datos de participación
  2. Datos agronómicos (productores, productoras y evaluadores): Variedades y Degustación
  3. Datos técnicos: distribuciones, manejo (multivalor), completitud y tabla de datos
"""
import logging
import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stAppDeployButton {display: none;}
    </style>
    """, unsafe_allow_html=True)

load_dotenv()
st.set_page_config(page_title="Bioleft · Tablero de ensayos", page_icon="🍅", layout="wide")

# --- CONFIGURACIÓN GLOBAL DE COLORES ---
# Se utiliza VIRIDIS, ya que es perceptualmente uniforme y estándar.
# En un futuro se puede crear una paleta propia tanto para atributos continuos como categóricos
# y que respete los colores de la organización.
PALETA_CONTINUA = px.colors.sequential.Viridis
PALETA_DISCRETA = px.colors.sample_colorscale(PALETA_CONTINUA, [x / 10 for x in range(1, 10)])
COLOR_PRINCIPAL = PALETA_DISCRETA[3]

VISTA = "v_ensayos_ancho"
SEP = " | "  # separador de las variables multivalor en la vista (string_agg)

URL_PLATAFORMA = "https://bioleft.org"  # Para responder a ¿Dónde consigo esta variedad? o si quieren ver algo
URL_ZENODO = "https://zenodo.org"       # poner el DOI de la versión 2 cuando se publique

MIN_ENSAYOS_DEFAULT = 3
MIN_ENSAYOS_MAX = 30


# Métricas muy asimétricas: el boxplot arranca en escala logarítmica.
LOG_POR_DEFECTO = ("total_frutos_cosechados", "peso_total_cosechado_kg")

# --- Diccionarios
METRICAS = {
    "emergencia_pct": "Emergencia (%)",
    "peso_total_cosechado_kg": "Peso total cosechado (kg)",
    "total_frutos_cosechados": "Frutos cosechados",
    "dias_siembra_a_cosecha": "Días de siembra a 1ª cosecha",
    "dias_siembra_a_floracion": "Días de siembra a 1ª floración",
    "sanidad": "Sanidad (1–5)",
    "uniformidad": "Uniformidad (1–5)",
    "tolerancia_estres_hidrico": "Tolerancia al estrés hídrico (1–5)",
    "tolerancia_quemadura_sol": "Tolerancia a quemadura de sol (1–5)",
    "gusto_general": "Gusto general (1–9)",
    "duracion_poscosecha_dias": "Duración poscosecha (días)",
}
CATEG = {
    "campana": "Campaña", "provincia": "Provincia",
    "ubicacion_parcela": "Ubicación de la parcela", "ubicacion_contenedor": "Ubicación del contenedor",
    "riego": "Riego", "conduccion": "Conducción", "metodo_siembra": "Método de siembra",
    "tutorado": "Tutorado", "desbrote": "Desbrote", "raleo_frutos": "Raleo de frutos",
    "eliminacion_brote_apical": "Eliminación del brote apical",
}
MULTI = {
    "sustrato": "Sustrato", "cultivo_asociado_maceta": "Cultivo asociado (maceta)",
    "cultivo_asociado_suelo": "Cultivo asociado (suelo)", "fertilizacion": "Fertilización",
    "control_plagas": "Control de plagas", "control_malezas": "Control de malezas",
    "cobertura_suelo": "Cobertura de suelo", "sanidad_observada": "Sanidad observada",
    "causa_desuniformidad": "Causa de (des)uniformidad",
    "causa_muerte_plantas": "Causa de muerte de plantas",
}
ETIQUETAS = {**METRICAS, **CATEG, **MULTI}
ATRIBUTOS = [
    "dulce", "acido", "aguachento", "jugoso", "mucha_pulpa", "poca_pulpa", "mucha_semilla",
    "poca_semilla", "olor_tomate_maduro", "olor_tomate_verde", "pastoso", "persistente",
    "piel_dura", "pulpa_blanda", "pulpa_dura",
]
ATRIB_ETIQ = {  # nombres legibles para el público
    "dulce": "Dulce", "acido": "Ácido", "aguachento": "Aguachento", "jugoso": "Jugoso",
    "mucha_pulpa": "Mucha pulpa", "poca_pulpa": "Poca pulpa", "mucha_semilla": "Muchas semillas",
    "poca_semilla": "Pocas semillas", "olor_tomate_maduro": "Olor a tomate maduro",
    "olor_tomate_verde": "Olor a tomate verde", "pastoso": "Pastoso", "persistente": "Persistente",
    "piel_dura": "Piel dura", "pulpa_blanda": "Pulpa blanda", "pulpa_dura": "Pulpa dura",
}
NUMERICAS = [
    "uniformidad", "sanidad", "tolerancia_estres_hidrico", "tolerancia_quemadura_sol", "gusto_general",
    "peso_total_cosechado_kg", "total_frutos_cosechados", "duracion_poscosecha_dias",
    "cantidad_semillas_sembradas", "cantidad_plantulas_emergidas",
]
FECHAS = [
    "fecha_siembra", "fecha_emergencia", "fecha_trasplante_maceta", "fecha_trasplante_suelo",
    "fecha_primera_floracion", "fecha_primera_cosecha", "fecha_ultima_cosecha",
]


def etiqueta(col: str) -> str:
    return ETIQUETAS.get(col, col.replace("_", " ").capitalize())


def etiqueta_atrib(col: str) -> str:
    return ATRIB_ETIQ.get(col, col.replace("_", " ").capitalize())


# --- CARGA DE DATOS
def obtener_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        try:
            url = st.secrets["DATABASE_URL"]  # Streamlit Cloud
        except Exception:
            url = None
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


@st.cache_data(ttl=600, show_spinner="Cargando datos…")
def cargar_desde_neon(url: str) -> pd.DataFrame:
    engine = create_engine(url, pool_pre_ping=True)  # pre_ping: Neon duerme el compute
    try:
        with engine.connect() as con:
            return pd.read_sql(text(f"SELECT * FROM {VISTA}"), con)
    finally:
        engine.dispose()


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in NUMERICAS:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in FECHAS:
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in CATEG:
        if c in df and df[c].notna().any() and df[c].dropna().isin([True, False]).all():
            df[c] = df[c].map({True: "Sí", False: "No"})
    # derivadas
    if {"cantidad_semillas_sembradas", "cantidad_plantulas_emergidas"} <= set(df):
        e = df["cantidad_plantulas_emergidas"] / df["cantidad_semillas_sembradas"] * 100
        df["emergencia_pct"] = e.where(e.between(0, 100))
    for nuevo, fin in [("dias_siembra_a_cosecha", "fecha_primera_cosecha"), ("dias_siembra_a_floracion", "fecha_primera_floracion")]:
        if {"fecha_siembra", fin} <= set(df):
            d = (df[fin] - df["fecha_siembra"]).dt.days
            df[nuevo] = d.where(d.between(1, 400))
    # Si no hay nombre_variedad, se usa solo la variedad (queda pendiente cargarlo a la base de datos)
    if "variedad_id" in df:
        k = df["variedad_id"].astype(str)
        if "nombre_variedad" in df:
            rot = k + " · " + df["nombre_variedad"].astype("string")
        else:
            rot = k
        df["variedad"] = rot.fillna(k).where(df["variedad_id"].notna())
        
    return df


def cargar() -> pd.DataFrame:
    url = obtener_url()
    if not url:
        st.error("Falta configurar DATABASE_URL (archivo .env en local, Secrets en Streamlit Cloud).")
        st.stop()
    try:
        return preparar(cargar_desde_neon(url))
    except Exception:
        logging.exception("No se pudo leer %s", VISTA)  # el detalle queda en el log, no en pantalla
        st.error("No se pudieron cargar los datos. Probá de nuevo en unos minutos.")
        st.stop()


def explotar(df: pd.DataFrame, col: str) -> pd.DataFrame:
    x = df[["ensayo_id", "campana", col]].dropna(subset=[col]).copy()
    x[col] = x[col].astype(str).str.split(SEP, regex=False)
    x = x.explode(col)
    x[col] = x[col].astype(str).str.strip()  # Limpia espacios extra al separar
    return x.rename(columns={col: "valor"})


# --- DATOS + FILTROS
df = cargar()
st.sidebar.title("🍅 Bioleft")

st.sidebar.header("Filtros")
camp = st.sidebar.multiselect("Campaña", sorted(df["campana"].dropna().unique()), default=sorted(df["campana"].dropna().unique()))
prov = st.sidebar.multiselect("Provincia", sorted(df["provincia"].dropna().unique()))
rot_var = df.drop_duplicates("variedad_id").set_index("variedad_id")["variedad"]
var = st.sidebar.multiselect("Variedad", sorted(df["variedad_id"].dropna().unique()), format_func=lambda v: rot_var.get(v, str(v)))

st.sidebar.divider()
st.sidebar.link_button("¿Dónde consigo estas variedades?", URL_PLATAFORMA)
st.sidebar.link_button("Datos publicados en Zenodo", URL_ZENODO)

f = df[df["campana"].isin(camp)]
if prov:
    f = f[f["provincia"].isin(prov)]
if var:
    f = f[f["variedad_id"].isin(var)]

st.title("Ensayos agronómicos participativos")
st.warning("**Proyecto en construcción.** Muchas variedades tienen pocos ensayos, insuficientes para sacar conclusiones. "
           "Antes de comparar, mirá siempre cuántos ensayos hay detrás de cada dato.")
if f.empty:
    st.warning("Los filtros no devuelven ensayos.")
    st.stop()

metricas = {k: v for k, v in METRICAS.items() if k in f and f[k].notna().any()}
categ = {k: v for k, v in CATEG.items() if k in f and f[k].notna().any()}
multi = {k: v for k, v in MULTI.items() if k in f and f[k].notna().any()}

t_part, t_agro, t_tec = st.tabs(["Datos de participación", "Datos agronómicos", "Datos técnicos"])

# ----- DATOS DE PARTICIPACIÓN
with t_part:
    st.caption("Quiénes participan y cuántos ensayos se hicieron.")
    c = st.columns(5)
    c[0].metric("Ensayos", f["ensayo_id"].nunique())
    c[1].metric("Participantes", f["id_participante"].nunique())
    c[2].metric("Sitios", f["id_sitio"].nunique())
    c[3].metric("Variedades", f["variedad_id"].nunique())
    c[4].metric("Provincias", f["provincia"].nunique())

    a, b = st.columns(2)
    por_camp = f.groupby("campana")["ensayo_id"].nunique().sort_index().reset_index(name="ensayos")
    por_camp["acumulado"] = por_camp["ensayos"].cumsum()
    a.plotly_chart(px.bar(por_camp, x="campana", y="acumulado", text="acumulado", title="Ensayos acumulados a la fecha",
                          labels={"campana": "Campaña", "acumulado": "Ensayos"},
                          color_discrete_sequence=[COLOR_PRINCIPAL]), width="stretch")
    a.caption("*Cada barra suma los ensayos de esa campaña y de las anteriores.*")

    por_prov = f.groupby("provincia")["ensayo_id"].nunique().sort_values().reset_index(name="ensayos")
    b.plotly_chart(px.bar(por_prov, x="ensayos", y="provincia", orientation="h", text="ensayos", title="Ensayos por provincia",
                          labels={"ensayos": "Ensayos", "provincia": ""},
                          color_discrete_sequence=[PALETA_DISCRETA[5]]), width="stretch")

    n_top = st.slider("Variedades a mostrar", 5, 10, 10)
    top = f.groupby("variedad")["ensayo_id"].nunique().nlargest(n_top).sort_values().reset_index(name="ensayos")
    st.plotly_chart(px.bar(top, x="ensayos", y="variedad", orientation="h", text="ensayos", title=f"Variedades más ensayadas (top {n_top})",
                           labels={"ensayos": "Ensayos", "variedad": ""},
                           color="ensayos", color_continuous_scale=PALETA_CONTINUA), width="stretch")

    # GÉNERO (indicador que Bioleft reporta a financiadores) 
    if "genero_participante" in f and f["genero_participante"].notna().any():
        st.subheader("Participantes por género")
        gen = f.dropna(subset=["genero_participante"]).groupby("genero_participante")["id_participante"].nunique().reset_index(name="participantes")

        # Porcentaje respecto al total de participantes con género declarado
        gen["porcentaje"] = (gen["participantes"] / gen["participantes"].sum() * 100).round(1)

        fig_gen = px.bar(
            gen,
            x="genero_participante",
            y="porcentaje",
            text="porcentaje",
            hover_data={"participantes": True, "porcentaje": False},
            title="Participantes por género (%)",
            labels={"genero_participante": "Género", "porcentaje": "%", "participantes": "Total de personas"},
            color="genero_participante",
            color_discrete_sequence=PALETA_DISCRETA,
        )
        fig_gen.update_traces(texttemplate="%{text}%")
        st.plotly_chart(fig_gen, width="stretch")

# ----- DATOS AGRONÓMICOS
with t_agro:
    st.caption("Para productores, productoras y evaluadores: qué variedades rinden y cuáles gustan más.")
    # Se muestran todas las variedades; cada persona decide desde cuántos ensayos con dato quiere mirar.
    n_min = st.slider("Mínimo de ensayos con dato por variedad", 1, MIN_ENSAYOS_MAX, MIN_ENSAYOS_DEFAULT,
                      help="Subí este valor para ver solo variedades con más ensayos (resultados más confiables).")
    sub_var, sub_deg = st.tabs(["Variedades", "Degustación"])

    # VARIEDADES
    with sub_var:
        c1, c2, c3 = st.columns([2, 1, 1])
        m = c1.selectbox("Métrica", list(metricas), format_func=etiqueta, key="v_m")
        agg = c2.radio("Resumen", ["Mediana", "Promedio"], horizontal=True)
        top_v = c3.selectbox("Mostrar", ["Todas", "Top 5", "Top 10"], help="Para ir de lo general a lo específico.")
        g = f.groupby("variedad")[m].agg(n="count", valor="median" if agg == "Mediana" else "mean").reset_index()
        g = g[g["n"] >= n_min].sort_values("valor", ascending=False)
        if top_v != "Todas":
            g = g.head(int(top_v.split()[1]))
        if g.empty:
            st.info("Ninguna variedad llega al mínimo de ensayos con ese dato.")
        else:
            fig = px.bar(g.iloc[::-1], x="valor", y="variedad", orientation="h", text="n", hover_data={"n": True},
                         labels={"valor": f"{agg} · {etiqueta(m)}", "variedad": ""},
                         title=f"{etiqueta(m)} por variedad", height=max(350, 24 * len(g) + 120),
                         color="valor", color_continuous_scale=PALETA_CONTINUA)
            fig.update_yaxes(type="category")
            st.plotly_chart(fig, width="stretch")
            st.caption("El número en cada barra es la cantidad de ensayos con dato.")

        d1, d2 = st.columns(2)
        mx = d1.selectbox("Eje X", list(metricas), format_func=etiqueta, index=min(3, len(metricas) - 1), key="sx")
        my = d2.selectbox("Eje Y", list(metricas), format_func=etiqueta, index=min(5, len(metricas) - 1), key="sy")
        sc = f.groupby("variedad").agg(x=(mx, "mean"), y=(my, "mean"), n=("ensayo_id", "nunique")).dropna().query("n >= @n_min").reset_index()
        st.plotly_chart(px.scatter(sc, x="x", y="y", size="n", hover_name="variedad", title="Correlaciones agronómicas",
                                   labels={"x": etiqueta(mx), "y": etiqueta(my)},
                                   color="y", color_continuous_scale=PALETA_CONTINUA), width="stretch")
        st.caption("Una burbuja representa una variedad; el tamaño indica la cantidad de ensayos.")

    # DEGUSTACIÓN
    with sub_deg:
        inten = pd.DataFrame({a: pd.to_numeric(f[a + "_intensidad"], errors="coerce") for a in ATRIBUTOS if a + "_intensidad" in f})
        inten = inten.dropna(axis=1, how="all")
        if inten.empty:
            st.info("Todavía no hay datos de degustación en escala de 1 a 9 con los filtros actuales.")
        else:
            atr = st.selectbox("Atributo", list(inten.columns), format_func=etiqueta_atrib)
            g = inten[atr].groupby(f["variedad"]).agg(n="count", promedio="mean").reset_index()
            g = g[g["n"] >= n_min].nlargest(3, "promedio")
            if g.empty:
                st.info("Ninguna variedad llega al mínimo de ensayos con ese dato (probá bajarlo o cambiar los filtros).")
            else:
                g["etiqueta"] = g["variedad"] + " (n=" + g["n"].astype(str) + ")"
                st.plotly_chart(px.bar(g.iloc[::-1], x="promedio", y="etiqueta", orientation="h", text_auto=".1f",
                                       title=f"Top 3 de variedades · {etiqueta_atrib(atr)}",
                                       labels={"promedio": "Promedio (escala 1–9)", "etiqueta": ""},
                                       color="promedio", color_continuous_scale=PALETA_CONTINUA), width="stretch")
                st.caption("Promedio en la escala de 1 a 9; n = ensayos con dato. Solo campañas que usaron esta escala.")

            with st.expander("Ver todos los atributos por variedad"):
                n_var = inten.notna().any(axis=1).groupby(f["variedad"]).sum()
                mat = inten.groupby(f["variedad"]).mean()
                mat = mat[n_var.reindex(mat.index) >= n_min].dropna(how="all")
                if mat.empty:
                    st.info("No hay datos con los filtros actuales.")
                else:
                    mat = mat.loc[n_var.reindex(mat.index).sort_values(ascending=False).index]
                    st.plotly_chart(px.imshow(mat.rename(columns=etiqueta_atrib), text_auto=".1f", aspect="auto",
                                              color_continuous_scale=PALETA_CONTINUA,
                                              height=max(350, 24 * len(mat) + 120), labels={"color": "Prom."},
                                              title="Promedio por atributo y variedad (escala 1–9)"), width="stretch")
                    sel = st.selectbox("Perfil de una variedad vs. el promedio", list(mat.index))
                    atrs = list(mat.columns)
                    prom = inten.mean()
                    cmp_ = pd.DataFrame({"atributo": [etiqueta_atrib(a) for a in atrs] * 2,
                                         "valor": list(mat.loc[sel].reindex(atrs)) + list(prom.reindex(atrs)),
                                         "serie": [sel] * len(atrs) + ["Promedio general"] * len(atrs)})
                    st.plotly_chart(px.bar(cmp_, x="atributo", y="valor", color="serie", barmode="group",
                                           title=f"Perfil de {sel} vs. el promedio general",
                                           labels={"atributo": "", "valor": "Promedio (1–9)", "serie": ""},
                                           color_discrete_sequence=[COLOR_PRINCIPAL, "#cccccc"]), width="stretch")

# ----- DATOS TÉCNICOS
with t_tec:
    st.caption("Para quienes quieran revisar cómo se midió: distribuciones, prácticas de manejo y calidad de los datos.")
    sub_dist, sub_man, sub_dat = st.tabs(["Distribuciones", "Manejo (multivalor)", "Completitud y datos"])

    # DISTRIBUCIONES (boxplots)
    with sub_dist:
        c1, c2, c3 = st.columns([2, 2, 1])
        gcol = c1.selectbox("Agrupar por", list(categ), format_func=etiqueta, index=list(categ).index("campana") if "campana" in categ else 0)
        mm = c2.selectbox("Métrica", list(metricas), format_func=etiqueta, key="p_m")
        log = c3.checkbox("Escala log", value=mm in LOG_POR_DEFECTO)
        d = f[[gcol, mm]].dropna().copy()
        if d.empty:
            st.info("Sin datos para esa combinación.")
        else:
            n = d.groupby(gcol)[mm].size()
            d["grupo"] = d[gcol].astype(str) + " (n=" + d[gcol].map(n).astype(str) + ")"
            orden = sorted(d["grupo"].unique()) if gcol == "campana" else list(d.groupby("grupo")[mm].size().sort_values(ascending=False).index)
            st.plotly_chart(px.box(d, x="grupo", y=mm, points="all", log_y=log, category_orders={"grupo": orden},
                                   title=f"{etiqueta(mm)} según {etiqueta(gcol).lower()}",
                                   labels={"grupo": etiqueta(gcol), mm: etiqueta(mm)},
                                   color="grupo", color_discrete_sequence=PALETA_DISCRETA), width="stretch")
            st.caption("Cada punto es un ensayo; la caja resume la distribución.")

    # ---------------------------------------------------------------- Manejo multivalor
    with sub_man:
        if not multi:
            st.info("La vista no trae variables multivalor.")
        else:
            c1, c2 = st.columns([3, 1])
            mv = c1.selectbox("Variable", list(multi), format_func=etiqueta)
            por_c = c2.checkbox("Separar por campaña")
            ex = explotar(f, mv)
            base = f[f[mv].notna()]
            
            if por_c:
                cnt = ex.groupby(["campana", "valor"])["ensayo_id"].nunique().reset_index(name="k")
                fig = px.bar(
                    cnt, x="k", y="valor", color="campana", orientation="h", barmode="group",
                    text="k", hover_data={"k": True},
                    color_discrete_sequence=PALETA_DISCRETA,
                    labels={"k": "Cantidad de ensayos", "valor": "", "campana": "Campaña"}
                )
                fig.update_traces(texttemplate='%{text}')
            else:
                cnt = ex.groupby("valor")["ensayo_id"].nunique().reset_index(name="k")
                cnt = cnt.sort_values("k")
                
                fig = px.bar(
                    cnt, x="k", y="valor", orientation="h", text="k", hover_data={"k": True},
                    color="k", color_continuous_scale=PALETA_CONTINUA,
                    labels={"k": "Cantidad de ensayos", "valor": ""}
                )
                fig.update_traces(texttemplate='%{text}')
            
            fig.update_layout(
                title=f"{etiqueta(mv)}: opciones elegidas", 
                xaxis_title="Cantidad de ensayos", 
                yaxis_title=None,
                barmode="group"
            )
            st.plotly_chart(fig, width="stretch")
            st.caption(f"Base: {base['ensayo_id'].nunique()} ensayos con dato en esta variable. Se podía marcar más de una opción. "
                       "En campañas viejas algunas categorías no existían.")
            
            cm = st.selectbox("Cruzar con una métrica", list(metricas), format_func=etiqueta, key="mv_m")
            x = ex.merge(f[["ensayo_id", cm]], on="ensayo_id").dropna(subset=[cm])
            if not x.empty:
                st.plotly_chart(px.box(x, x=cm, y="valor", points="all", title=f"{etiqueta(cm)} según {etiqueta(mv).lower()}",
                                       labels={cm: etiqueta(cm), "valor": ""},
                                       color="valor", color_discrete_sequence=PALETA_DISCRETA), width="stretch")
                
    # COMPLETITUD Y DATOS
    with sub_dat:
        cols = [c for c in list(metricas) + list(categ) + list(multi) + [a + x for a in ATRIBUTOS for x in ("_marcado", "_intensidad")] + FECHAS if c in f and c != "campana"]
        comp = f.groupby("campana")[cols].apply(lambda g: g.notna().mean() * 100).T
        st.plotly_chart(px.imshow(comp, text_auto=".0f", aspect="auto", color_continuous_scale=PALETA_CONTINUA, height=max(400, 20 * len(comp) + 100),
                                  zmin=0, zmax=100, title="Porcentaje de respuesta por campaña",
                                  labels={"color": "% con dato", "x": "Campaña", "y": ""}), width="stretch")
        st.caption("% de ensayos con dato en cada variable. Maceta vs. suelo y cambios de planilla entre campañas explican parte de los vacíos.")
        st.subheader("Tabla filtrada (formato ancho)")
        st.dataframe(f, width="stretch", hide_index=True)
        st.download_button("Descargar CSV", f.to_csv(index=False).encode("utf-8"), "ensayos_ancho_filtrado.csv", "text/csv")
        if st.button("Recargar datos"):
            st.cache_data.clear()
            st.rerun()
