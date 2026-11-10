"""
procesar_comentarios.py
=======================
Recupera (o corrige) observaciones usando el texto de `comentarios_generales`, sin inventar filas.

Idea general
------------
1. Las REGLAS viven en un CSV editable (reglas_comentarios.csv): "si el comentario dice X -> variable V = valor Y".
2. Cada coincidencia pasa por filtros de certeza:
      - incertidumbre ("creo", "me parece", "capaz", "?" ...)  -> DESCARTADA_INCIERTA (no se agrega nunca)
      - negación ("no hubo", "sin", "nunca" ...)               -> REVISAR_NEGADO
      - valor que no existe en el catálogo de esa variable      -> DESCARTADA_FUERA_CATALOGO
      - el comentario menciona variedades (V7, "variedad")      -> REVISAR_ALCANCE
      - dos valores distintos para una variable de 1 valor      -> REVISAR_AMBIGUO
      - el comentario corrige respuestas previas ("no son exactas") -> REVISAR_CORRECCION
   La NEGACIÓN se interpreta según la regla:
      - si la regla tiene `valor_si_negado` (ej. "No" en desbrote/tutorado/raleo...), "no hice raleo" propone raleo = "No"
        (y entra al mismo circuito de certeza/conflicto que cualquier otra propuesta);
      - si no lo tiene y la variable es multivalor ("no tuvo pulgones"): si el valor ya está cargado queda REVISAR_NEGADO
        (el dato contradice el comentario), si no está cargado queda NEGADO_SIN_ACCION (no hay nada que hacer);
      - si no lo tiene y la variable es de un solo valor: REVISAR_NEGADO.
3. Política de conflictos (qué dato manda):
      - la variable NO tiene respuesta en ese ensayo            -> AUTO_APLICADA (se agrega la fila)
      - ya tiene EXACTAMENTE ese valor                           -> REDUNDANTE (no se toca)
      - ya tiene otra respuesta                                  -> REVISAR_CONFLICTO (NUNCA se pisa solo)
   Lo que queda en REVISAR_* se resuelve a mano en un CSV de decisiones (agregar / reemplazar / ignorar)
   y esas decisiones se reutilizan en las corridas siguientes (campañas futuras incluidas).
   `exportar_pendientes(..., archivo_decisiones=...)` archiva las decisiones ya escritas antes de regenerar el CSV de
   pendientes, así que volver a exportar NO pierde lo que ya se resolvió.
4. Toda fila recuperada lleva en `nota` "Recuperado de comentario [regla] (comentario en etapa 'X')" -> se puede auditar y revertir.

Uso mínimo
----------
    from procesar_comentarios import (procesar_comentarios, exportar_pendientes, resumen, comentarios_sin_regla,
                                      auditar_cambios)

    decisiones = ['decisiones_comentarios.csv', 'pendientes_comentarios.csv']   # archivo persistente + lo recién completado
    df_nuevo, informe = procesar_comentarios(df_final, 'reglas_comentarios.csv', decisiones)
    resumen(informe)
    auditar_cambios(df_final, df_nuevo)                              # qué filas se agregaron/quitaron y chequeos de coherencia
    exportar_pendientes(informe, 'pendientes_comentarios.csv', archivo_decisiones='decisiones_comentarios.csv')
    comentarios_sin_regla(df_nuevo, 'reglas_comentarios.csv')       # comentarios que ninguna regla cubre (para escribir reglas nuevas)

Texto: todo comentario se compara en minúsculas y sin tildes (`normalizar`). Los patrones del CSV también se pasan
por ahí, así que da lo mismo escribir "arañuela" o "aranuela".
"""
import hashlib
import os
import re
import unicodedata
import warnings
from collections import Counter, defaultdict

import pandas as pd

# ----------------------------------------------------------------------------
# Configuración (se puede pasar otra a procesar_comentarios si cambia el esquema)
# ----------------------------------------------------------------------------
VERSION = '2026-10-30.3'   # se imprime en resumen(): sirve para comprobar que se está corriendo el archivo actualizado

VARIABLE_COMENTARIOS = 'comentarios_generales'
CLAVE_BASE = ['campaña', 'id_participante', 'id_sitio', 'sub_ensayo', 'variedad_id']
# Columna extra que completa la clave del ensayo según la versión del dataset: antes se llamaba `variedad_original`
# (etiqueta de texto); en el dataset final pasó a `anio_multiplicacion` (casi todo nulo). Se usa la que exista.
COLUMNAS_EXTRA_CLAVE = ('variedad_original', 'anio_multiplicacion')
CLAVE_ENSAYO = CLAVE_BASE + ['variedad_original']      # solo por compatibilidad con código viejo: el script usa _clave_ensayo(df)
VARIABLES_MULTIVALOR = {'sustrato', 'cultivo_asociado_maceta', 'cultivo_asociado_suelo',
                        'sanidad_observada', 'fertilizacion', 'control_plagas', 'causa_desuniformidad'}
# Valores que equivalen a "no respondió" (se pueden reemplazar con un comentario confirmado)
VALORES_SIN_RESPUESTA = {'condicion_poscosecha': {'No especificado'}, 'metodo_siembra': {'Almácigo (genérico)'}}
# Respuestas "ninguno" explícitas: si el comentario dice otra cosa, es un conflicto que se resuelve reemplazando
VALORES_NINGUNO = {'sanidad_observada': {'No se observó ningún problema'}, 'fertilizacion': {'No utilicé'},
                   'control_plagas': {'No realicé control'},
                   'cultivo_asociado_maceta': {'No hubo'}, 'cultivo_asociado_suelo': {'No hubo'}}
PREFIJO_NOTA = 'Recuperado de comentario'

# Léxicos (sobre texto normalizado: minúsculas y sin tildes)
RE_INCERTIDUMBRE = re.compile(
    r"\b(cre(?:o|emos|ia|iamos|e|en|eria|eriamos)|me parec\w*|parec\w*|quiza|quizas|tal vez|capaz|puede ser|"
    r"algun (?:virus|hongo|bicho|insecto|plaga|enfermedad)|"
    r"podria|podrian|posibl\w*|probabl\w*|supongo|supondria|imagino|sospecho|sospecha|presum\w*|intuy\w*|intuicion|"
    r"(?:pienso|pensamos|pense|pensaba|pensabamos) que|diria\w*|(?:sensacion|impresion) (?:de )?que|impresion de|"
    r"duda|dudo|no se si|no sabemos si|no sabr\w+|no estoy segur[oa]|(?:no tengo|sin|poca) certeza|"
    r"no pude confirmar|no confirmo|no logre identificar|a lo mejor|si no me equivoco|si mal no recuerdo|"
    r"habr(?:a|an|ia|ian)|aparentemente|al parecer|seguramente|como si|algo asi|tendria|"
    r"deb(?:e|en|io|ieron|eria|erian) (?:ser|haber)|pud(?:o|ieron|iera|ieran) (?:ser|haber)|pued(?:e|en) haber|"
    r"supuestamente|me dio la impresion|"
    # dato provisional o recomendación general: no es un hecho cerrado sobre ESTE ensayo
    r"por ahora|hasta ahora|hasta el momento|por el momento|"
    r"lo ideal|conviene|se recomienda|recomiendo|habria que|deberia\w*|lo mejor es|hay que)\b|\?")
RE_NEGACION = re.compile(r"\b(no|sin|nunca|ningun|ninguna|ninguno|ni|tampoco|jamas)\b|libre de|ausencia de|falta de|faltaron?|carencia de|no pude|no llegue a")
RE_ADVERSATIVA = re.compile(r"\bpero\b|\bsino\b|\baunque\b|\bsin embargo\b|\bno obstante\b|\bsi bien\b")
RE_VARIEDAD = re.compile(r"\bv\d{1,3}\b|\bvariedad(es)?\b")
# "No hubo problemas con plagas, tutorado ...": esa negación es sobre plagas/problemas, NO sobre lo que viene después
RE_NEGACION_NEUTRA = re.compile(
    r"\b(?:no|sin|nunca)\s+(?:\w+\s+)?(?:problemas?|inconvenientes?|novedades?|plagas?|enfermedades?)\b"
    r"(?:\s+(?:con|de|por)\s+(?:plagas?|insectos?|enfermedades?|hongos?|riego|agua))?")
# El comentario avisa que corrige/aclara respuestas anteriores: nada se aplica solo
RE_CORRECCION = re.compile(
    r"respuestas? (?:que )?no (?:son|es) (?:del todo )?exact\w*|no es exactamente|no son exactas|"
    r"me equivoque|\bcorrijo\b|\bcorreccion\b|\baclaro que\b|en realidad")

ORDEN_CALIDAD = {'confirmado': 0, 'negado': 1, 'incierto': 2}


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def normalizar(texto):
    """Minúsculas, sin tildes ni ñ, sin tabs (también el '\\t' literal que traen algunos comentarios), espacios colapsados."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ''
    t = str(texto).replace('\\t', ' ').replace('\t', ' ')
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', t).strip()


def _nn(x):
    """NaN / NA / NaT -> None. Imprescindible para usar la clave del ensayo en diccionarios y sets: dos NaN nunca son
    iguales (nan != nan), así que un ensayo con `anio_multiplicacion` nulo jamás encontraba sus propias respuestas."""
    try:
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return x


def _clave_ensayo(df):
    """Columnas que identifican un ensayo en ESTE dataset: la base + (variedad_original | anio_multiplicacion) si existe."""
    return CLAVE_BASE + [c for c in COLUMNAS_EXTRA_CLAVE if c in df.columns][:1]


def _sin_tildes(texto):
    """Quita tildes/ñ SIN pasar a minúsculas (en regex, \\W y \\w no son lo mismo)."""
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode()


def _hash(*partes):
    return hashlib.sha1('|'.join(str(p) for p in partes).encode('utf-8')).hexdigest()[:10]


def _lista(celda):
    """'a|b|c' -> {'a','b','c'} ; vacío -> set()"""
    if celda is None or (isinstance(celda, float) and pd.isna(celda)) or str(celda).strip() == '':
        return set()
    return {x.strip() for x in str(celda).split('|') if x.strip()}


def cargar_reglas(reglas):
    """
    Acepta ruta a CSV o DataFrame. Columnas: regla_id, variable, valor, patron
    Opcionales: etapas (solo en esas), etapas_excluidas, campañas, excluir_comentario (regex: si matchea el comentario
    ENTERO, la regla no se aplica; sirve para descartar contextos como "sustrato Growmix ... compost"),
    valor_si_negado (si el comentario NIEGA la acción —"no hice raleo", "sin tutorado"— se propone este valor en vez
    de descartar; típico: "No" para las variables Sí/No).
    Los patrones se aplican sobre texto normalizado (minúsculas, sin tildes). Acá se les sacan las tildes por si se
    escribieron con ellas ("arañuela" funciona igual que "aranuela").
    """
    r = pd.read_csv(reglas, dtype=str, keep_default_na=False) if isinstance(reglas, (str, os.PathLike)) else reglas.copy()
    r = r.fillna('').astype(str)   # un DataFrame con celdas vacías (NaN) se comporta igual que el CSV
    faltan = {'regla_id', 'variable', 'valor', 'patron'} - set(r.columns)
    if faltan:
        raise ValueError(f"Al archivo de reglas le faltan columnas: {sorted(faltan)}")
    for c in ('etapas', 'etapas_excluidas', 'campañas', 'excluir_comentario', 'valor_si_negado'):
        if c not in r.columns:
            r[c] = ''
    if r['regla_id'].duplicated().any():
        raise ValueError(f"regla_id repetidos: {r.loc[r['regla_id'].duplicated(), 'regla_id'].tolist()}")
    out = []
    for fila in r.itertuples(index=False):
        try:
            pat = re.compile(_sin_tildes(fila.patron), re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Regla {fila.regla_id}: patrón inválido ({e})")
        out.append(dict(regla_id=fila.regla_id, variable=fila.variable, valor=fila.valor, pat=pat,
                        etapas=_lista(fila.etapas), excluidas=_lista(fila.etapas_excluidas), campanas=_lista(fila.campañas),
                        valor_negado=str(fila.valor_si_negado).strip(),
                        excluir=(re.compile(_sin_tildes(fila.excluir_comentario), re.IGNORECASE)
                                 if str(fila.excluir_comentario).strip() else None)))
    return out


def _leer_decisiones(fuente):
    if fuente is None:
        return None
    if isinstance(fuente, (str, os.PathLike)):
        if not os.path.exists(fuente):
            warnings.warn(f"No se encontró el archivo de decisiones '{os.path.abspath(fuente)}': se ignora. "
                          f"Si lo tenés con otro nombre o en otra carpeta, ajustá la ruta.", stacklevel=4)
            return None
        d = pd.read_csv(fuente, dtype=str, keep_default_na=False, encoding='utf-8-sig')
        if d.shape[1] == 1 and ';' in str(d.columns[0]):      # Excel en español guarda los CSV separados por ';'
            d = pd.read_csv(fuente, dtype=str, keep_default_na=False, encoding='utf-8-sig', sep=';')
        return d
    return fuente.copy()


def cargar_decisiones(decisiones):
    """
    Acepta ruta a CSV (si existe), DataFrame, o una LISTA de ellos (se juntan; sirve para pasar a la vez el archivo
    persistente de decisiones y el CSV de pendientes que se acaba de completar).
    Columnas: grupo_id y/o propuesta_id, decision (agregar|reemplazar|ignorar). Si una misma propuesta/grupo
    aparece con decisiones distintas, vale la última fuente de la lista.
    """
    fuentes = decisiones if isinstance(decisiones, (list, tuple)) else [decisiones]
    por_prop, por_grupo = {}, {}
    for fuente in fuentes:
        d = _leer_decisiones(fuente)
        if d is None or d.empty:
            continue
        # si el archivo tiene filas pero no las columnas clave, NO se ignora en silencio: se avisa
        if 'decision' not in d.columns or not ({'grupo_id', 'propuesta_id'} & set(d.columns)):
            raise ValueError(f"El archivo de decisiones no tiene las columnas esperadas (decision y grupo_id/propuesta_id). "
                             f"Columnas leídas: {list(d.columns)}. ¿Se guardó con otro separador o se borró el encabezado?")
        for c in ('grupo_id', 'propuesta_id'):
            if c not in d.columns:
                d[c] = ''
        d = d[d['decision'].astype(str).str.strip().str.lower() != 'decision']   # encabezado repetido por un copiar/pegar
        d['decision'] = d['decision'].astype(str).str.strip().str.lower()
        malas = d[(d['decision'] != '') & ~d['decision'].isin(['agregar', 'reemplazar', 'ignorar'])]
        if len(malas):
            raise ValueError(f"Decisiones inválidas (usar agregar / reemplazar / ignorar): {malas['decision'].unique().tolist()}")
        d = d[d['decision'] != '']
        por_prop.update({r.propuesta_id: r.decision for r in d.itertuples() if str(r.propuesta_id).strip()})
        por_grupo.update({r.grupo_id: r.decision for r in d.itertuples()
                          if str(r.grupo_id).strip() and not str(r.propuesta_id).strip()})
    return por_prop, por_grupo


# ----------------------------------------------------------------------------
# Evaluación de un comentario contra las reglas
# ----------------------------------------------------------------------------
def _evaluar_comentario(texto, etapa, campana, reglas, alcance_incertidumbre, ningunos=None):
    """
    Devuelve (hallazgos, menciona_variedad, es_correccion).
    hallazgos = {(variable, valor): (calidad, regla_id, detalle)} con la MEJOR evidencia de cada par.
    """
    norm = normalizar(texto)
    oraciones = [o.strip() for o in re.split(r'[.;!\n]+', norm) if o.strip()]
    hallazgos = {}
    for r in reglas:
        if r['etapas'] and etapa not in r['etapas']:
            continue
        if etapa in r['excluidas']:
            continue
        if r['campanas'] and campana not in r['campanas']:
            continue
        if r['excluir'] and r['excluir'].search(norm):
            continue
        for oracion in oraciones:
            m = r['pat'].search(oracion)
            if not m:
                continue
            antes = RE_ADVERSATIVA.split(oracion[:m.start()])[-1]
            antes = RE_NEGACION_NEUTRA.sub(' ', antes)          # "no hubo problemas con plagas, tutorado..." no niega el tutorado
            ventana = ' '.join(antes.split()[-10:])
            dudoso = RE_INCERTIDUMBRE.search(norm if alcance_incertidumbre == 'comentario' else oracion)
            negado = RE_NEGACION.search(ventana)
            k = (r['variable'], r['valor'])
            if dudoso:
                ev = ('incierto', r['regla_id'], f"duda: '{dudoso.group(0)}'")
            elif negado and r['valor_negado']:
                # "no hice raleo" -> raleo = No: es una afirmación confirmada sobre el valor contrario
                k = (r['variable'], r['valor_negado'])
                ev = ('confirmado', r['regla_id'], f"negación -> '{r['valor_negado']}': '{negado.group(0)}' + '{m.group(0)}'")
            elif negado:
                ev = ('negado', r['regla_id'], f"negación: '{negado.group(0)}'")
            else:
                ev = ('confirmado', r['regla_id'], f"coincide: '{m.group(0)}'")
            if k not in hallazgos or ORDEN_CALIDAD[ev[0]] < ORDEN_CALIDAD[hallazgos[k][0]]:
                hallazgos[k] = ev

    # "No tuve problemas con plagas" + "tuve problemas con cuy y una liebre" no pueden valer a la vez:
    # si el mismo comentario confirma otro valor real, el valor "ninguno" se descarta.
    for variable, vals_ninguno in (ningunos or {}).items():
        reales = [k for k, ev in hallazgos.items() if k[0] == variable and k[1] not in vals_ninguno and ev[0] == 'confirmado']
        if reales:
            for k in [k for k in hallazgos if k[0] == variable and k[1] in vals_ninguno]:
                del hallazgos[k]

    menciona_variedad = bool(RE_VARIEDAD.search(norm))
    es_correccion = bool(RE_CORRECCION.search(norm))
    return hallazgos, menciona_variedad, es_correccion


# ----------------------------------------------------------------------------
# Función principal
# ----------------------------------------------------------------------------
def procesar_comentarios(df, reglas, decisiones=None, *,
                         alcance_incertidumbre='comentario',
                         revisar_si_menciona_variedad=True,
                         permitir_valores_nuevos=False,
                         variables_multivalor=None,
                         valores_sin_respuesta=None,
                         valores_ninguno=None):
    """
    Devuelve (df_nuevo, informe). `df` es el dataset en formato largo (el de df_final):
    columnas de la clave del ensayo (CLAVE_BASE + variedad_original o anio_multiplicacion) + etapa, variable, valor, nota.

    decisiones: ruta a CSV, DataFrame o LISTA de ellos (ver cargar_decisiones).
    alcance_incertidumbre: 'comentario' (default, conservador: una duda en CUALQUIER parte del comentario lo descarta)
                           u 'oracion' (solo cuenta la duda de la misma oración que la coincidencia).
    """
    multivalor = set(VARIABLES_MULTIVALOR if variables_multivalor is None else variables_multivalor)
    sin_resp = VALORES_SIN_RESPUESTA if valores_sin_respuesta is None else valores_sin_respuesta
    ningunos = VALORES_NINGUNO if valores_ninguno is None else valores_ninguno

    clave = _clave_ensayo(df)
    faltan = set(CLAVE_BASE + ['etapa', 'variable', 'valor', 'nota']) - set(df.columns)
    if faltan:
        raise ValueError(f"Al DataFrame le faltan columnas: {sorted(faltan)}")

    reglas_c = cargar_reglas(reglas)
    por_prop, por_grupo = cargar_decisiones(decisiones)

    comentarios = df[df['variable'] == VARIABLE_COMENTARIOS]
    resto = df[df['variable'] != VARIABLE_COMENTARIOS]
    existentes = {tuple(_nn(x) for x in k): v
                  for k, v in resto.groupby(clave + ['variable'], dropna=False)['valor'].apply(list).to_dict().items()}
    etapa_de = resto.groupby('variable')['etapa'].agg(lambda s: s.mode().iloc[0]).to_dict()
    catalogo = resto.groupby('variable')['valor'].agg(lambda s: set(s.dropna())).to_dict()

    # --- 1) propuestas (una por ensayo x variable x valor) --------------------------------------
    cache = {}
    propuestas = []
    for c in comentarios.itertuples(index=False):
        texto = getattr(c, 'valor')
        if pd.isna(texto) or str(texto).strip() == '':
            continue
        campana, etapa = getattr(c, 'campaña'), getattr(c, 'etapa')
        k = (campana, etapa, texto)
        if k not in cache:
            cache[k] = _evaluar_comentario(texto, etapa, campana, reglas_c, alcance_incertidumbre, ningunos)
        hallazgos, menciona_var, es_correccion = cache[k]
        ensayo = tuple(_nn(getattr(c, col)) for col in clave)
        e = dict(zip(clave, ensayo))
        for (variable, valor), (calidad, regla_id, detalle) in hallazgos.items():
            propuestas.append(dict(
                ensayo=ensayo, **e,
                etapa_comentario=etapa, variable=variable, valor_propuesto=valor, calidad=calidad, regla_id=regla_id,
                detalle=detalle, menciona_variedad=menciona_var, es_correccion=es_correccion,
                comentario=str(texto).strip(), comentario_normalizado=normalizar(texto),
                grupo_id=_hash(campana, e['id_sitio'], variable, valor, normalizar(texto)),
                propuesta_id=_hash(*ensayo, variable, valor, normalizar(texto))))
    # un mismo comentario puede estar duplicado en el mismo ensayo: nos quedamos con una propuesta
    vistos, unicas = set(), []
    for p in propuestas:
        if p['propuesta_id'] in vistos:
            continue
        vistos.add(p['propuesta_id'])
        unicas.append(p)
    propuestas = unicas

    # --- 2) ambigüedad: variable de 1 valor con 2+ valores confirmados distintos ----------------
    por_ensayo_var = defaultdict(set)
    for p in propuestas:
        if p['calidad'] == 'confirmado' and p['variable'] not in multivalor:
            por_ensayo_var[(p['ensayo'], p['variable'])].add(p['valor_propuesto'])

    # --- 3) estado de cada propuesta ------------------------------------------------------------
    for p in propuestas:
        var, val, ens = p['variable'], p['valor_propuesto'], p['ensayo']
        actuales = existentes.get(ens + (var,), [])
        placeholders = set(sin_resp.get(var, set()))
        efectivos = [a for a in actuales if a not in placeholders]
        es_ninguno = val in ningunos.get(var, set())
        p['valores_existentes'] = '; '.join(map(str, actuales))
        p['accion_sugerida'] = ''
        p['placeholder_a_quitar'] = [a for a in actuales if a in placeholders]
        p['efectivos'] = efectivos

        if p['calidad'] == 'incierto':
            p['estado'] = 'DESCARTADA_INCIERTA'
        elif p['calidad'] == 'negado':
            if var in multivalor and val not in efectivos:
                p['estado'] = 'NEGADO_SIN_ACCION'        # niega algo que tampoco está cargado: no hay nada que corregir
            else:
                p['estado'] = 'REVISAR_NEGADO'
                if var in multivalor:
                    p['detalle'] += ' | el valor ya está cargado: ¿el dato es incorrecto?'
        elif not permitir_valores_nuevos and val not in catalogo.get(var, set()):
            p['estado'] = 'DESCARTADA_FUERA_CATALOGO'
            p['detalle'] += f" | '{val}' no está en el catálogo de {var}"
        elif val in efectivos:
            p['estado'] = 'REDUNDANTE'                   # ya está cargado: aunque el alcance sea dudoso, no hay nada que aplicar
        elif revisar_si_menciona_variedad and p['menciona_variedad']:
            p['estado'] = 'REVISAR_ALCANCE'
            p['detalle'] += ' | el comentario menciona variedades: ¿aplica a todas?'
        elif len(por_ensayo_var.get((ens, var), ())) > 1:
            p['estado'] = 'REVISAR_AMBIGUO'
            p['detalle'] += f" | el comentario sugiere {sorted(por_ensayo_var[(ens, var)])}"
        elif not efectivos:
            p['estado'] = 'REVISAR_CORRECCION' if p['es_correccion'] else 'AUTO_APLICADA'
            if p['es_correccion']:
                p['detalle'] += ' | el comentario dice que corrige/aclara respuestas anteriores'
        else:
            p['estado'] = 'REVISAR_CONFLICTO'

        if p['estado'].startswith('REVISAR'):
            if p['estado'] == 'REVISAR_NEGADO' and var in multivalor:
                p['accion_sugerida'] = 'ignorar'          # el comentario no agrega nada; el dato cargado es lo que hay que mirar
            elif es_ninguno and efectivos and not set(efectivos) <= ningunos.get(var, set()):
                p['accion_sugerida'] = 'ignorar'          # "no hubo plagas" vs. plagas concretas ya cargadas: gana lo concreto
            elif var in multivalor and efectivos and not set(efectivos) <= ningunos.get(var, set()):
                p['accion_sugerida'] = 'agregar'
            else:
                p['accion_sugerida'] = 'reemplazar' if efectivos else 'agregar'

    # --- 3b) otro comentario del MISMO ensayo ya aplica ese mismo valor solo: no hay nada que revisar ------
    # (las propuestas se evaluaron contra el dataset original, así que no se "veían" entre sí)
    ya_auto = {(p['ensayo'], p['variable'], p['valor_propuesto']) for p in propuestas if p['estado'] == 'AUTO_APLICADA'}
    for p in propuestas:
        if p['estado'] in ('REVISAR_ALCANCE', 'REVISAR_AMBIGUO', 'REVISAR_CORRECCION') \
                and (p['ensayo'], p['variable'], p['valor_propuesto']) in ya_auto:
            p['estado'] = 'REDUNDANTE'
            p['accion_sugerida'] = ''
            p['detalle'] += ' | ya se aplica solo desde otro comentario del mismo ensayo'

    # --- 4) decisiones manuales sobre lo que quedó en REVISAR_* ---------------------------------
    for p in propuestas:
        p['decision'] = ''
        if not p['estado'].startswith('REVISAR'):
            continue
        d = por_prop.get(p['propuesta_id']) or por_grupo.get(p['grupo_id'])
        if not d:
            continue
        p['decision'] = d
        if d == 'ignorar':
            p['estado'] = 'IGNORADA_POR_DECISION'
        elif d == 'agregar' and p['variable'] not in multivalor and p['efectivos']:
            p['estado'] = 'ERROR_DECISION'
            p['detalle'] += ' | "agregar" dejaría 2 valores en una variable de un solo valor: usar "reemplazar" o "ignorar"'
        elif (d == 'agregar' and p['valor_propuesto'] in ningunos.get(p['variable'], set())
              and any(v not in ningunos[p['variable']] for v in p['efectivos'])):
            p['estado'] = 'ERROR_DECISION'
            p['detalle'] += f" | \"agregar\" '{p['valor_propuesto']}' junto a valores concretos ya cargados es contradictorio: usar \"reemplazar\" o \"ignorar\""

        else:
            p['estado'] = 'APLICADA_POR_DECISION'
            p['decision_efectiva'] = d

    ids_prop = {p['propuesta_id'] for p in propuestas}
    ids_grupo = {p['grupo_id'] for p in propuestas}
    huerfanas = [k for k in por_prop if k not in ids_prop] + [k for k in por_grupo if k not in ids_grupo]
    if huerfanas:
        warnings.warn(f"{len(huerfanas)} decisiones no coinciden con ninguna propuesta actual y NO se aplicaron "
                      f"(¿cambió el dataset, una regla o el texto del comentario?). Ejemplos: {huerfanas[:3]}", stacklevel=2)

    # --- 5) aplicar -----------------------------------------------------------------------------
    nuevas, reemplazar_todo, quitar_valor = [], set(), set()
    ya = set()
    for p in propuestas:
        if p['estado'] not in ('AUTO_APLICADA', 'APLICADA_POR_DECISION'):
            continue
        clave_fila = (p['ensayo'], p['variable'], p['valor_propuesto'])
        if clave_fila in ya:
            continue
        ya.add(clave_fila)
        nota = f"{PREFIJO_NOTA} [{p['regla_id']}]"
        if not pd.isna(p['etapa_comentario']) and str(p['etapa_comentario']).strip():
            nota += f" (comentario en etapa '{p['etapa_comentario']}')"     # la fila queda en la etapa de la variable, no en esta
        if p['estado'] == 'APLICADA_POR_DECISION':
            nota += ' | decisión manual: ' + p['decision_efectiva']
            if p['decision_efectiva'] == 'reemplazar':
                reemplazar_todo.add((p['ensayo'], p['variable']))
                # "reemplazar" borra TODOS los valores de esa variable en el ensayo: queda registrado cuáles eran
                quitados = [v for v in dict.fromkeys(existentes.get(p['ensayo'] + (p['variable'],), [])) if v != p['valor_propuesto']]
                if quitados:
                    nota += ' | reemplaza ' + ', '.join(f"'{v}'" for v in quitados)
            elif p['valor_propuesto'] not in ningunos.get(p['variable'], set()):
                # "agregar" una plaga a un ensayo que decía "Ninguna": el "Ninguna" ya no puede quedar
                for v in existentes.get(p['ensayo'] + (p['variable'],), []):
                    if v in ningunos.get(p['variable'], set()):
                        quitar_valor.add((p['ensayo'], p['variable'], v))
                        nota += f" | quita '{v}'"

        else:
            for ph in p['placeholder_a_quitar']:
                quitar_valor.add((p['ensayo'], p['variable'], ph))
            if p['placeholder_a_quitar']:
                nota += f" | reemplaza '{p['placeholder_a_quitar'][0]}'"
        fila = {c: pd.NA for c in df.columns}
        fila.update(dict(zip(clave, p['ensayo'])))             # incluye sub_ensayo: la fila nueva queda en el mismo sub-ensayo
        fila.update(etapa=etapa_de.get(p['variable'], p['etapa_comentario']), variable=p['variable'],
                    valor=p['valor_propuesto'], nota=nota)
        nuevas.append(fila)

    base = df
    if reemplazar_todo or quitar_valor:
        claves = [tuple(_nn(x) for x in t) for t in zip(*[base[c] for c in clave])]
        borrar = [((k, v) in reemplazar_todo) or ((k, v, val) in quitar_valor)
                  for k, v, val in zip(claves, base['variable'], base['valor'])]
        base = base[~pd.Series(borrar, index=base.index)]
    resultado = pd.concat([base, pd.DataFrame(nuevas, columns=df.columns)], ignore_index=True) if nuevas else base.reset_index(drop=True)
    for c in clave:                                            # que sub_ensayo (u otra clave) no cambie de tipo al concatenar
        try:
            resultado[c] = resultado[c].astype(df[c].dtype)
        except (TypeError, ValueError):
            pass

    # --- 6) informe -----------------------------------------------------------------------------
    cols = ['estado', 'accion_sugerida', 'decision'] + clave + ['etapa_comentario', 'variable', 'valor_propuesto', 'valores_existentes',
            'regla_id', 'detalle', 'comentario', 'comentario_normalizado', 'grupo_id', 'propuesta_id']
    informe = pd.DataFrame(propuestas)
    informe = informe[cols] if len(informe) else pd.DataFrame(columns=cols)
    return resultado, informe


# ----------------------------------------------------------------------------
# Salidas auxiliares
# ----------------------------------------------------------------------------
def resumen(informe):
    """Cuenta propuestas por estado (cada fila = un ensayo)."""
    print(f'procesar_comentarios versión {VERSION}\n')
    if informe.empty:
        print('Sin propuestas.')
        return
    print(informe['estado'].value_counts().to_string())
    print('\nPor variable (solo lo aplicado):')
    ap = informe[informe['estado'].isin(['AUTO_APLICADA', 'APLICADA_POR_DECISION'])]
    print(ap.groupby(['variable', 'valor_propuesto']).size().to_string() if len(ap) else '  (nada)')


def _rescatar_decisiones(ruta_pendientes, archivo_decisiones):
    """
    Antes de regenerar el CSV de pendientes: lo que ya tiene `decision` escrita se copia (sin duplicar) al archivo
    persistente de decisiones. Así volver a exportar no pierde el trabajo manual. Devuelve cuántas filas se guardaron.
    """
    if not archivo_decisiones or not os.path.exists(ruta_pendientes):
        return 0
    viejo = pd.read_csv(ruta_pendientes, dtype=str, keep_default_na=False)
    if 'decision' not in viejo.columns:
        return 0
    viejo = viejo[viejo['grupo_id'].str.strip() != 'grupo_id']          # encabezado repetido por un copiar/pegar
    hechas = viejo[viejo['decision'].str.strip() != ''].copy()
    if hechas.empty:
        return 0
    for c in ('grupo_id', 'propuesta_id'):
        if c not in hechas.columns:
            hechas[c] = ''
    previas = (pd.read_csv(archivo_decisiones, dtype=str, keep_default_na=False)
               if os.path.exists(archivo_decisiones) else pd.DataFrame(columns=hechas.columns))
    todas = pd.concat([previas, hechas], ignore_index=True)
    todas['_k'] = todas['propuesta_id'].where(todas['propuesta_id'].str.strip() != '', todas['grupo_id'])
    todas = todas.drop_duplicates('_k', keep='last').drop(columns='_k')      # si cambió de idea, vale la decisión más nueva
    todas.to_csv(archivo_decisiones, index=False, encoding='utf-8-sig')
    return len(hechas)


def exportar_pendientes(informe, ruta='pendientes_comentarios.csv', archivo_decisiones=None):
    """
    Escribe lo que hay que revisar a mano, agrupado por comentario (un comentario repetido en 5 variedades = 1 fila).
    Completar la columna `decision` con agregar / reemplazar / ignorar y pasar ese CSV como `decisiones`.
    Si se pasa `archivo_decisiones`, las decisiones ya escritas en el CSV anterior se guardan ahí antes de pisarlo.
    """
    n_guardadas = _rescatar_decisiones(ruta, archivo_decisiones)
    if n_guardadas:
        print(f'{n_guardadas} decisiones del CSV anterior archivadas en {archivo_decisiones}')
    pend = informe[informe['estado'].str.startswith('REVISAR') | (informe['estado'] == 'ERROR_DECISION')]
    if pend.empty:
        print('No hay pendientes.')
        pd.DataFrame(columns=['grupo_id', 'estado', 'decision', 'propuesta_id']).to_csv(ruta, index=False, encoding='utf-8-sig')
        return pend
    g = (pend.groupby('grupo_id', sort=False)
         .agg(estado=('estado', 'first'), accion_sugerida=('accion_sugerida', 'first'), campaña=('campaña', 'first'),
              id_sitio=('id_sitio', 'first'), etapa_comentario=('etapa_comentario', 'first'),
              variable=('variable', 'first'), valor_propuesto=('valor_propuesto', 'first'),
              n_ensayos=('propuesta_id', 'nunique'),
              valores_existentes=('valores_existentes', lambda s: ' || '.join(sorted(set(s)))),
              regla_id=('regla_id', 'first'), detalle=('detalle', 'first'), comentario=('comentario', 'first'))
         .reset_index().sort_values(['estado', 'n_ensayos'], ascending=[True, False]))
    g['decision'] = ''
    g['propuesta_id'] = ''   # opcional: decidir por un ensayo puntual en vez de por todo el grupo
    g.to_csv(ruta, index=False, encoding='utf-8-sig')
    print(f'{len(g)} comentarios únicos para revisar -> {ruta}')
    return g


def comentarios_sin_regla(df, reglas, alcance_incertidumbre='comentario'):
    """
    Comentarios que NINGUNA regla reconoce, con frecuencia por campaña (para decidir qué reglas escribir).
    Se agrupan por texto NORMALIZADO ("Crecimiento normal" y "crecimiento normal" cuentan juntos).
    """
    reglas_c = cargar_reglas(reglas)
    com = df[df['variable'] == VARIABLE_COMENTARIOS][['campaña', 'etapa', 'valor']].dropna()
    com = com.assign(norm=com['valor'].map(normalizar))
    com = com[com['norm'] != '']
    filas = []
    for (camp, etapa, norm), sub in com.groupby(['campaña', 'etapa', 'norm']):
        hall, _, _ = _evaluar_comentario(sub['valor'].iloc[0], etapa, camp, reglas_c, alcance_incertidumbre)
        if not hall:
            filas.append(dict(campaña=camp, etapa=etapa, comentario=str(sub['valor'].iloc[0]).strip(),
                              comentario_normalizado=norm, frecuencia=len(sub)))
    out = pd.DataFrame(filas, columns=['campaña', 'etapa', 'comentario', 'comentario_normalizado', 'frecuencia'])
    return out.sort_values('frecuencia', ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Auditoría: qué cambió realmente entre el dataset original y el procesado
# ----------------------------------------------------------------------------
def auditar_cambios(df_antes, df_despues, verbose=True):
    """
    Compara los dos datasets y devuelve (cambios, problemas):
      - cambios: DataFrame con filas AGREGADAS y QUITADAS por variable/valor (para ver que solo se tocó lo esperado).
      - problemas: lista de textos con lo que no cierra (vacía = todo bien).
    Chequeos: filas agregadas sin nota de recuperación, sub_ensayo nulo, valores fuera del catálogo previo,
    duplicados nuevos y variables de 1 valor que quedaron con 2+ valores en un ensayo donde antes tenían 1.
    """
    clave = _clave_ensayo(df_despues)
    cols = clave + ['etapa', 'variable', 'valor']
    ca = Counter(map(tuple, df_antes[cols].astype(str).values.tolist()))
    cd = Counter(map(tuple, df_despues[cols].astype(str).values.tolist()))
    agregadas, quitadas = cd - ca, ca - cd
    filas = [('AGREGADA', f[-2], f[-1], n) for f, n in agregadas.items()] + \
            [('QUITADA', f[-2], f[-1], n) for f, n in quitadas.items()]
    cambios = (pd.DataFrame(filas, columns=['cambio', 'variable', 'valor', 'filas'])
               .groupby(['cambio', 'variable', 'valor'], as_index=False)['filas'].sum()
               .sort_values(['cambio', 'variable', 'valor']).reset_index(drop=True))
    problemas = []

    nuevas = df_despues[df_despues['nota'].fillna('').str.startswith(PREFIJO_NOTA)]
    n_nuevas_total = sum(agregadas.values())
    # Solo cuentan las notas de filas NUEVAS: si el dataset ya traía filas recuperadas en una corrida anterior
    # (ej. el CSV final exportado), esas no se pueden contar como "agregadas ahora".
    # se compara por clave SIN el texto de la nota: una fila recuperada en una corrida anterior cuya nota se regeneró
    # (ej. ahora con la etapa) es la misma fila, no una nueva
    cn = lambda d: Counter(map(tuple, d[d['nota'].fillna('').str.startswith(PREFIJO_NOTA)][cols].astype(str).values.tolist()))
    n_con_nota = sum((cn(df_despues) - cn(df_antes)).values())
    if n_nuevas_total != n_con_nota:
        problemas.append(f"Filas agregadas ({n_nuevas_total}) != filas nuevas con nota '{PREFIJO_NOTA}' "
                         f"({n_con_nota}): se agregó algo sin dejar nota o la nota quedó en filas viejas.")
    if nuevas['sub_ensayo'].isna().any():
        problemas.append(f"{int(nuevas['sub_ensayo'].isna().sum())} filas recuperadas con sub_ensayo nulo.")
    previo = df_antes[df_antes['variable'] != VARIABLE_COMENTARIOS]
    catalogo = previo.groupby('variable')['valor'].agg(lambda s: set(s.dropna())).to_dict()
    fuera = nuevas[[v not in catalogo.get(var, set()) for var, v in zip(nuevas['variable'], nuevas['valor'])]]
    if len(fuera):
        problemas.append(f"{len(fuera)} filas recuperadas con valor fuera del catálogo previo: "
                         f"{fuera.groupby(['variable', 'valor']).size().to_dict()}")
    dup_antes = df_antes.duplicated(cols).sum()
    dup_despues = df_despues.duplicated(cols).sum()
    if dup_despues > dup_antes:
        problemas.append(f"Aparecieron {dup_despues - dup_antes} filas duplicadas (misma clave + variable + valor).")

    def _multi_por_ensayo(d):
        x = d[d['variable'] != VARIABLE_COMENTARIOS].groupby(clave + ['variable'], dropna=False)['valor'].nunique()
        return {tuple(_nn(v) for v in i) for i in x[x > 1].index}
    ya_multi = _multi_por_ensayo(df_antes)
    nuevos_multi = [i for i in _multi_por_ensayo(df_despues)
                    if i not in ya_multi and i[-1] not in VARIABLES_MULTIVALOR]
    if nuevos_multi:
        problemas.append(f"{len(nuevos_multi)} ensayos quedaron con 2+ valores en variables de un solo valor: "
                         f"{sorted({i[-1] for i in nuevos_multi})}")

    if verbose:
        print(f"Filas: {len(df_antes)} -> {len(df_despues)}  (+{sum(agregadas.values())} / -{sum(quitadas.values())})")
        print(cambios.to_string(index=False) if len(cambios) else '  (sin cambios)')
        print('\nChequeos:', 'OK, sin problemas' if not problemas else '')
        for p in problemas:
            print('  [!]', p)
    return cambios, problemas
