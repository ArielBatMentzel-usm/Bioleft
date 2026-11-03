"""Bioleft · Tablero de ensayos agronómicos participativos (Streamlit).

Lee UNA vista ancha de Neon (v_ensayos_ancho, 1 fila por ensayo) y arma todos los
tableros en pandas/plotly. Si no hay DATABASE_URL (o falla), cae a los CSV de data/.
"""
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
st.set_page_config(page_title="Bioleft · Tablero de ensayos", page_icon="🍅", layout="wide")

VISTA = "v_ensayos_ancho"
DATA_DIR = Path(__file__).parent / "data"
SEP = " | "  # separador de las variables multivalor en la vista (string_agg)

# ---------------------------------------------------------------- diccionarios
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
ATRIBUTOS = [
    "dulce", "acido", "aguachento", "jugoso", "mucha_pulpa", "poca_pulpa", "mucha_semilla",
    "poca_semilla", "olor_tomate_maduro", "olor_tomate_verde", "pastoso", "persistente",
    "piel_dura", "pulpa_blanda", "pulpa_dura",
]
NUMERICAS = [
    "uniformidad", "sanidad", "tolerancia_estres_hidrico", "tolerancia_quemadura_sol", "gusto_general",
    "peso_total_cosechado_kg", "total_frutos_cosechados", "duracion_poscosecha_dias",
    "cantidad_semillas_sembradas", "cantidad_plantulas_emergidas",
]
FECHAS = [
    "fecha_siembra", "fecha_emergencia", "fecha_trasplante_maceta", "fecha_trasplante_suelo",
    "fecha_primera_floracion", "fecha_primera_cosecha", "fecha_ultima_cosecha",
]
SINO = {"sí": 1, "si": 1, "true": 1, "no": 0, "false": 0}


def etiqueta(col: str) -> str:
    return {**METRICAS, **CATEG, **MULTI}.get(col, col.replace("_", " ").capitalize())


# ---------------------------------------------------------------- carga de datos
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


@st.cache_data(ttl=600, show_spinner="Leyendo Neon…")
def cargar_desde_neon(url: str) -> pd.DataFrame:
    engine = create_engine(url, pool_pre_ping=True)  # pre_ping: Neon duerme el compute
    try:
        with engine.connect() as con:
            return pd.read_sql(text(f"SELECT * FROM {VISTA}"), con)
    finally:
        engine.dispose()


@st.cache_data(show_spinner="Leyendo CSV…")
def cargar_desde_csv() -> pd.DataFrame:
    """Replica en pandas lo que hace la vista: largo -> ancho, 1 fila por ensayo."""
    o = pd.read_csv(DATA_DIR / "observaciones_agronomicas_limpio.csv")
    s = pd.read_csv(DATA_DIR / "sitios_ubicacion.csv")
    o = o[o["variable"] != "comentarios_generales"]
    clave = ["campaña", "id_participante", "id_sitio", "sub_ensayo", "variedad_id", "anio_multiplicacion"]
    o = o.assign(anio_multiplicacion=o["anio_multiplicacion"].fillna(-1))
    ancho = (
        o.groupby(clave + ["variable"])["valor"]
        .agg(lambda v: SEP.join(dict.fromkeys(v.dropna().astype(str))))
        .unstack("variable")
        .replace("", pd.NA)
        .reset_index()
    )
    ancho["anio_multiplicacion"] = ancho["anio_multiplicacion"].replace(-1, pd.NA)
    ancho = ancho.rename(columns={"campaña": "campana"})
    for a in ATRIBUTOS:  # la base guarda marcado (bool) e intensidad (1-9) por separado
        if a in ancho:
            ancho[a + "_marcado"] = ancho[a].map({"Sí": True, "No": False})
            ancho[a + "_intensidad"] = pd.to_numeric(ancho[a].where(~ancho[a].isin(["Sí", "No"])), errors="coerce")
    ancho = ancho.drop(columns=[a for a in ATRIBUTOS if a in ancho])
    ancho.insert(0, "ensayo_id", range(1, len(ancho) + 1))
    return ancho.merge(s[["sitio_id", "provincia", "localidad"]], left_on="id_sitio", right_on="sitio_id", how="left").drop(columns="sitio_id")


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={"campaña": "campana"}).copy()
    for c in ["ensayo_id", "id_participante", "id_sitio", "variedad_id", "campana", "provincia", "localidad"]:
        if c not in df:
            df[c] = pd.NA
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
    return df


def cargar():
    url = obtener_url()
    if url:
        try:
            return preparar(cargar_desde_neon(url)), "Neon"
        except Exception as e:
            st.sidebar.error(f"No pude leer `{VISTA}` en Neon: {type(e).__name__}. Uso los CSV.")
            st.sidebar.caption(str(e).splitlines()[0][:200])
    if (DATA_DIR / "observaciones_agronomicas_limpio.csv").exists():
        return preparar(cargar_desde_csv()), "CSV local (data/)"
    st.error("No hay DATABASE_URL ni CSV en data/. Revisá el .env.")
    st.stop()


def explotar(df: pd.DataFrame, col: str) -> pd.DataFrame:
    x = df[["ensayo_id", "campana", col]].dropna(subset=[col]).copy()
    x[col] = x[col].astype(str).str.split(SEP, regex=False)
    return x.explode(col).rename(columns={col: "valor"})


# ---------------------------------------------------------------- datos + filtros
df, fuente = cargar()
st.sidebar.title("🍅 Bioleft")
st.sidebar.caption(f"Fuente: **{fuente}**")
if st.sidebar.button("Recargar datos"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.header("Filtros")
camp = st.sidebar.multiselect("Campaña", sorted(df["campana"].dropna().unique()), default=sorted(df["campana"].dropna().unique()))
prov = st.sidebar.multiselect("Provincia", sorted(df["provincia"].dropna().unique()))
var = st.sidebar.multiselect("Variedad", sorted(df["variedad_id"].dropna().unique()))
f = df[df["campana"].isin(camp)]
if prov:
    f = f[f["provincia"].isin(prov)]
if var:
    f = f[f["variedad_id"].isin(var)]
if f.empty:
    st.warning("Los filtros no devuelven ensayos.")
    st.stop()

metricas = {k: v for k, v in METRICAS.items() if k in f and f[k].notna().any()}
categ = {k: v for k, v in CATEG.items() if k in f and f[k].notna().any()}
multi = {k: v for k, v in MULTI.items() if k in f and f[k].notna().any()}

st.title("Ensayos agronómicos participativos")
t1, t2, t3, t4, t5, t6 = st.tabs(["Panorama", "Variedades", "Prácticas", "Manejo (multivalor)", "Degustación", "Datos"])

# ---------------------------------------------------------------- 1. Panorama
with t1:
    c = st.columns(5)
    c[0].metric("Ensayos", f["ensayo_id"].nunique())
    c[1].metric("Participantes", f["id_participante"].nunique())
    c[2].metric("Sitios", f["id_sitio"].nunique())
    c[3].metric("Variedades", f["variedad_id"].nunique())
    c[4].metric("Provincias", f["provincia"].nunique())
    a, b = st.columns(2)
    por_camp = f.groupby("campana")["ensayo_id"].nunique().reset_index(name="ensayos")
    a.plotly_chart(px.bar(por_camp, x="campana", y="ensayos", text="ensayos", title="Ensayos por campaña"), width="stretch")
    por_prov = f.groupby("provincia")["ensayo_id"].nunique().sort_values().reset_index(name="ensayos")
    b.plotly_chart(px.bar(por_prov, x="ensayos", y="provincia", orientation="h", text="ensayos", title="Ensayos por provincia"), width="stretch")
    top = f.groupby("variedad_id")["ensayo_id"].nunique().nlargest(20).sort_values().reset_index(name="ensayos")
    st.plotly_chart(px.bar(top, x="ensayos", y="variedad_id", orientation="h", text="ensayos", title="Variedades más ensayadas (top 20)"), width="stretch")

# ---------------------------------------------------------------- 2. Variedades
with t2:
    c1, c2, c3 = st.columns([2, 1, 1])
    m = c1.selectbox("Métrica", list(metricas), format_func=etiqueta, key="v_m")
    agg = c2.radio("Resumen", ["Mediana", "Promedio"], horizontal=True)
    n_min = c3.slider("Mínimo de ensayos con dato", 1, 10, 3)
    g = f.groupby("variedad_id")[m].agg(n="count", valor="median" if agg == "Mediana" else "mean").reset_index()
    g = g[g["n"] >= n_min].sort_values("valor", ascending=False)
    if g.empty:
        st.info("Ninguna variedad llega al mínimo de ensayos con ese dato.")
    else:
        fig = px.bar(g.head(30).iloc[::-1], x="valor", y="variedad_id", orientation="h", text="n",
                     hover_data={"n": True}, labels={"valor": f"{agg} · {etiqueta(m)}", "variedad_id": "Variedad"},
                     title=f"{etiqueta(m)} por variedad (el número en la barra = ensayos con dato)")
        fig.update_yaxes(type="category")
        st.plotly_chart(fig, width="stretch")
    st.subheader("Relación entre dos métricas (una burbuja por variedad)")
    d1, d2 = st.columns(2)
    mx = d1.selectbox("Eje X", list(metricas), format_func=etiqueta, index=min(3, len(metricas) - 1), key="sx")
    my = d2.selectbox("Eje Y", list(metricas), format_func=etiqueta, index=min(5, len(metricas) - 1), key="sy")
    sc = f.groupby("variedad_id").agg(x=(mx, "mean"), y=(my, "mean"), n=("ensayo_id", "nunique")).dropna().query("n >= @n_min").reset_index()
    st.plotly_chart(px.scatter(sc, x="x", y="y", size="n", hover_name="variedad_id",
                               labels={"x": etiqueta(mx), "y": etiqueta(my)}), width="stretch")

# ---------------------------------------------------------------- 3. Prácticas
with t3:
    c1, c2, c3 = st.columns([2, 2, 1])
    gcol = c1.selectbox("Agrupar por", list(categ), format_func=etiqueta, index=list(categ).index("campana") if "campana" in categ else 0)
    mm = c2.selectbox("Métrica", list(metricas), format_func=etiqueta, key="p_m")
    log = c3.checkbox("Escala log", value=mm in ("peso_total_cosechado_kg", "total_frutos_cosechados"))
    d = f[[gcol, mm]].dropna().copy()
    n = d.groupby(gcol)[mm].size()
    d["grupo"] = d[gcol].astype(str) + " (n=" + d[gcol].map(n).astype(str) + ")"
    orden = sorted(d["grupo"].unique()) if gcol == "campana" else list(d.groupby("grupo")[mm].size().sort_values(ascending=False).index)
    if d.empty:
        st.info("Sin datos para esa combinación.")
    else:
        st.plotly_chart(px.box(d, x="grupo", y=mm, points="all", log_y=log, category_orders={"grupo": orden},
                               labels={"grupo": etiqueta(gcol), mm: etiqueta(mm)}), width="stretch")
        st.caption("Cada punto es un ensayo. Ojo con los grupos de n chico: no alcanzan para concluir.")

# ---------------------------------------------------------------- 4. Manejo multivalor
with t4:
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
            cnt["pct"] = cnt["k"] / cnt["campana"].map(base.groupby("campana")["ensayo_id"].nunique()) * 100
            fig = px.bar(cnt, x="pct", y="valor", color="campana", orientation="h", barmode="group", hover_data={"k": True})
        else:
            cnt = ex.groupby("valor")["ensayo_id"].nunique().reset_index(name="k")
            cnt["pct"] = cnt["k"] / base["ensayo_id"].nunique() * 100
            fig = px.bar(cnt.sort_values("pct"), x="pct", y="valor", orientation="h", text=cnt.sort_values("pct")["k"], hover_data={"k": True})
        fig.update_layout(xaxis_title="% de ensayos que lo mencionan (pueden marcar más de una opción)", yaxis_title=None)
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Base: {base['ensayo_id'].nunique()} ensayos con dato en esta variable. En campañas viejas algunas categorías no existían.")
        st.subheader("Cruce con una métrica")
        cm = st.selectbox("Métrica", list(metricas), format_func=etiqueta, key="mv_m")
        x = explotar(f, mv).merge(f[["ensayo_id", cm]], on="ensayo_id").dropna(subset=[cm])
        if not x.empty:
            st.plotly_chart(px.box(x, x=cm, y="valor", points="all", labels={cm: etiqueta(cm), "valor": ""}), width="stretch")

# ---------------------------------------------------------------- 5. Degustación
with t5:
    c1, c2 = st.columns([2, 1])
    modo = c1.radio("Qué mostrar", ["Marcado: % de “Sí”", "Intensidad: promedio 1–9"], horizontal=True)
    n_min = c2.slider("Mínimo de ensayos por variedad", 1, 10, 3, key="d_n")
    binario = modo.startswith("Marcado")
    suf = "_marcado" if binario else "_intensidad"
    cols = {a: a + suf for a in ATRIBUTOS if a + suf in f}
    if not cols:
        st.info("La vista no trae atributos de degustación.")
    else:
        crudo = pd.DataFrame({a: f[c] for a, c in cols.items()})
        if binario:
            vals = crudo.apply(lambda s: s.astype(str).str.strip().str.lower().map(SINO)) * 100
        else:
            vals = crudo.apply(pd.to_numeric, errors="coerce")
        atrs = list(cols)
        n_var = vals.notna().any(axis=1).groupby(f["variedad_id"]).sum()
        mat = vals.groupby(f["variedad_id"]).mean()
        mat = mat[n_var.reindex(mat.index) >= n_min].dropna(how="all")
        if mat.empty:
            st.info("No hay datos de este tipo con los filtros actuales (probá otras campañas o bajá el mínimo).")
        else:
            mat = mat.loc[n_var.reindex(mat.index).sort_values(ascending=False).index]
            st.plotly_chart(px.imshow(mat.rename(columns=lambda c: c.replace("_", " ")), text_auto=".0f" if binario else ".1f",
                                      aspect="auto", color_continuous_scale="Blues", height=max(350, 24 * len(mat) + 120),
                                      labels={"color": "% Sí" if binario else "Prom."}), width="stretch")
            st.subheader("Perfil de una variedad vs. el promedio")
            sel = st.selectbox("Variedad", list(mat.index))
            prom = vals.mean()
            cmp_ = pd.DataFrame({"atributo": [a.replace("_", " ") for a in atrs] * 2,
                                 "valor": list(mat.loc[sel].reindex(atrs)) + list(prom.reindex(atrs)),
                                 "serie": [sel] * len(atrs) + ["Promedio general"] * len(atrs)})
            st.plotly_chart(px.bar(cmp_, x="atributo", y="valor", color="serie", barmode="group"), width="stretch")
        st.caption("La ficha cambió en 2025-2026 (de Sí/No a escala 1–9): ‘marcado’ cubre sobre todo las campañas viejas e ‘intensidad’ las nuevas. Filtrá por campaña para no mezclar.")

# ---------------------------------------------------------------- 6. Datos
with t6:
    cols = [c for c in list(metricas) + list(categ) + list(multi) + [a + x for a in ATRIBUTOS for x in ("_marcado", "_intensidad")] + FECHAS if c in f and c != "campana"]
    comp = f.groupby("campana")[cols].apply(lambda g: g.notna().mean() * 100).T
    st.subheader("Completitud por variable (% de ensayos con dato)")
    st.plotly_chart(px.imshow(comp, text_auto=".0f", aspect="auto", color_continuous_scale="Greens",
                              height=max(400, 20 * len(comp) + 100), zmin=0, zmax=100), width="stretch")
    st.caption("Maceta vs. suelo y cambios de planilla entre campañas explican parte de los vacíos.")
    st.subheader("Tabla filtrada (formato ancho)")
    st.dataframe(f, width="stretch", hide_index=True)
    st.download_button("Descargar CSV", f.to_csv(index=False).encode("utf-8"), "ensayos_ancho_filtrado.csv", "text/csv")
