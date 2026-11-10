"""
Pruebas de regresión de procesar_comentarios.py.
  - Las primeras usan un dataset sintético chico y reglas mínimas (no necesitan nada más).
  - Las que empiezan con test_reales_ usan reglas_comentarios.csv (el de verdad, al lado de este archivo) y, si lo
    encuentran, el CSV final de observaciones; si falta alguno de los dos, esa prueba se saltea.
Correr:  python test_procesar_comentarios.py     (o:  pytest test_procesar_comentarios.py)
Sirve para comprobar que al tocar el código o las reglas no se rompe lo que ya andaba.
"""
import os
import tempfile

import pandas as pd

import scripts.tratamiento_comentarios.procesar_comentarios as pc

AQUI = os.path.dirname(os.path.abspath(__file__))

# NaN a propósito: en el dataset final casi todo `anio_multiplicacion` es nulo y eso rompió las claves una vez
BASE = dict(campaña='2025-2026', id_participante='P1', id_sitio='S1', sub_ensayo=1,
            variedad_id='V1', anio_multiplicacion=float('nan'), nota=pd.NA)

CHICOS = 'Bichitos chicos (pulgones, arañuelas, chinches, etc)'
GRANDES = 'Bichos grandes (orugas, babosas, langostas, etc)'
POLVILLO = 'Polvillo blanco sobre las hojas'
AMARILLAS = 'Hojas amarillas, enruladas o deformadas'
HERB = 'Mordidas o picoteos de herbívoros/aves en frutos u hojas'
MORDIDAS = 'Hojas con caminitos, agujeros o mordidas'
NINGUNO = 'No se observó ningún problema'

# reglas mínimas (las reales viven en reglas_comentarios.csv)
REGLAS = pd.DataFrame([
    dict(regla_id='L03', variable='raleo_frutos', valor='Sí', patron=r'\braleo\b|\bralearon\b', valor_si_negado='No'),
    dict(regla_id='L01', variable='desbrote', valor='Sí', patron=r'desbrot', valor_si_negado='No'),
    dict(regla_id='L02', variable='tutorado', valor='Sí', patron=r'tutorad', valor_si_negado='No'),
    dict(regla_id='P01', variable='sanidad_observada', valor=CHICOS, patron='arañuela'),   # con ñ y tilde a propósito
    dict(regla_id='P02', variable='sanidad_observada', valor=CHICOS, patron=r'pulgon'),
    dict(regla_id='P10', variable='sanidad_observada', valor=HERB, patron=r'liebre'),
    dict(regla_id='P11', variable='sanidad_observada', valor=POLVILLO, patron=r'oidio'),
    # solo para probar la lógica de los valores "ninguno": el reglas_comentarios.csv real NO tiene esta regla
    # ("ninguna plaga" no implica "ningún problema de sanidad")
    dict(regla_id='PX', variable='sanidad_observada', valor=NINGUNO,
         patron=r'\b(?:no|sin)\s+(?:(?:hubo|hay|tuvo|tuve)\s+)?(?:problemas?\s+(?:con|de)\s+)?plagas?\b'),
]).assign(etapas='', etapas_excluidas='', campañas='', excluir_comentario='')


def fila(variable, valor, etapa='Labores', **kw):
    return {**BASE, 'etapa': etapa, 'variable': variable, 'valor': valor, **kw}


# el catálogo de cada variable sale de los valores que ya existen en el dataset: este ensayo "CAT" los aporta
CATALOGO = [fila('sanidad_observada', v, id_participante='CAT') for v in (CHICOS, POLVILLO, AMARILLAS, HERB, NINGUNO)] + \
           [fila(var, v, id_participante='CAT') for var in ('raleo_frutos', 'desbrote', 'tutorado') for v in ('Sí', 'No')]


def correr(filas, **kw):
    df = pd.DataFrame(filas + CATALOGO)
    return pc.procesar_comentarios(df, REGLAS, **kw)


def valores(res, variable, **filtro):
    m = (res['variable'] == variable) & (res['id_participante'] != 'CAT')
    for k, v in filtro.items():
        m &= res[k] == v
    return sorted(res.loc[m, 'valor'])


def estado(inf, variable, valor):
    return inf[(inf['variable'] == variable) & (inf['valor_propuesto'] == valor)]['estado'].tolist()


def test_normalizar():
    assert pc.normalizar('  Arañuela\tROJA\\t ') == 'aranuela roja'
    assert pc.normalizar(None) == '' and pc.normalizar(float('nan')) == ''


def test_negacion_propone_no_y_no_si():
    # "no hice raleo": propone raleo=No (no "Sí" dudoso)
    res, inf = correr([fila('comentarios_generales', 'No hice raleo de frutos'), fila('raleo_frutos', 'Sí')])
    assert estado(inf, 'raleo_frutos', 'No') == ['REVISAR_CONFLICTO'] and estado(inf, 'raleo_frutos', 'Sí') == []
    assert inf.loc[inf.valor_propuesto == 'No', 'accion_sugerida'].iloc[0] == 'reemplazar'
    # sin dato previo: se completa solo
    res, inf = correr([fila('comentarios_generales', 'no se hizo raleo'), fila('desbrote', 'Sí')])
    assert estado(inf, 'raleo_frutos', 'No') == ['AUTO_APLICADA'] and valores(res, 'raleo_frutos') == ['No']
    # coincide con lo cargado: redundante
    _, inf = correr([fila('comentarios_generales', 'No hubo raleo'), fila('raleo_frutos', 'No')])
    assert estado(inf, 'raleo_frutos', 'No') == ['REDUNDANTE']


def test_negacion_con_lista_y_adversativa():
    _, inf = correr([fila('comentarios_generales', 'sin tutorado ni desbrote'), fila('raleo_frutos', 'No')])
    assert estado(inf, 'tutorado', 'No') == ['AUTO_APLICADA'] and estado(inf, 'desbrote', 'No') == ['AUTO_APLICADA']
    _, inf = correr([fila('comentarios_generales', 'no hice raleo pero si desbrote'), fila('tutorado', 'Sí')])
    assert estado(inf, 'raleo_frutos', 'No') == ['AUTO_APLICADA'] and estado(inf, 'desbrote', 'Sí') == ['AUTO_APLICADA']


def test_no_hubo_problemas_no_niega_lo_que_sigue():
    _, inf = correr([fila('comentarios_generales', 'No hubo problemas con plagas, tutorado a dos aguas'),
                     fila('tutorado', 'Sí')])
    assert estado(inf, 'tutorado', 'Sí') == ['REDUNDANTE']
    assert estado(inf, 'tutorado', 'No') == []


def test_duda_y_provisorio_se_descartan():
    for txt in ('creo que tuvo arañuela', 'sin plagas por ahora', 'lo ideal es hacer raleo'):
        res, inf = correr([fila('comentarios_generales', txt), fila('tutorado', 'Sí')])
        assert set(inf['estado']) == {'DESCARTADA_INCIERTA'}, txt
        assert len(res) == 2 + len(CATALOGO)


def test_multivalor_negado():
    # niega algo que no está cargado: nada que hacer
    _, inf = correr([fila('comentarios_generales', 'No tuvo oídio'), fila('sanidad_observada', AMARILLAS)])
    assert estado(inf, 'sanidad_observada', POLVILLO) == ['NEGADO_SIN_ACCION']
    # niega algo que SÍ está cargado: a revisar (el dato contradice el comentario)
    _, inf = correr([fila('comentarios_generales', 'No tuvo oídio'), fila('sanidad_observada', POLVILLO)])
    assert estado(inf, 'sanidad_observada', POLVILLO) == ['REVISAR_NEGADO']


def test_ninguno():
    res, inf = correr([fila('comentarios_generales', 'Es un balcón, no hubo plagas'), fila('tutorado', 'Sí'),
                       fila('sanidad_observada', AMARILLAS, id_participante='P2'),
                       fila('comentarios_generales', 'no hubo plagas', id_participante='P2')])
    assert valores(res, 'sanidad_observada', id_participante='P1') == [NINGUNO]
    p2 = inf[inf.id_participante == 'P2'].iloc[0]
    assert p2['estado'] == 'REVISAR_CONFLICTO' and p2['accion_sugerida'] == 'ignorar'   # lo concreto gana a "ninguno"
    # "no tuve problemas con plagas, pero sí con una liebre": la liebre descarta al "ninguno"
    _, inf = correr([fila('comentarios_generales', 'No tuve problemas con plagas, pero si con una liebre'),
                     fila('sanidad_observada', AMARILLAS)])
    assert estado(inf, 'sanidad_observada', NINGUNO) == []


def test_patrones_con_tildes_y_comentarios_con_mayusculas():
    res, inf = correr([fila('comentarios_generales', 'ARAÑUELA roja!'), fila('tutorado', 'Sí')])
    assert valores(res, 'sanidad_observada') == [CHICOS]


def test_sub_ensayo_se_respeta():
    # dos sub-ensayos del mismo ensayo: el dato de uno no tapa al otro y la fila nueva hereda su sub_ensayo
    filas = [fila('comentarios_generales', 'aparecio arañuela', sub_ensayo=2),
             fila('sanidad_observada', CHICOS, sub_ensayo=1),
             fila('tutorado', 'Sí', sub_ensayo=2)]
    res, inf = correr(filas)
    assert inf['estado'].tolist() == ['AUTO_APLICADA']
    nueva = res[res['nota'].fillna('').str.startswith(pc.PREFIJO_NOTA)].iloc[0]
    assert int(nueva['sub_ensayo']) == 2 and res['sub_ensayo'].dtype.kind == 'i'


def test_nota_incluye_la_etapa_del_comentario():
    # la fila nueva queda en la etapa de la VARIABLE; la nota conserva en qué etapa estaba el COMENTARIO
    res, inf = correr([fila('comentarios_generales', 'aparecio arañuela', etapa='Cosecha'), fila('tutorado', 'Sí')])
    nueva = res[res['nota'].fillna('').str.startswith(pc.PREFIJO_NOTA)].iloc[0]
    assert nueva['nota'] == "Recuperado de comentario [P01] (comentario en etapa 'Cosecha')"
    # con decisión manual se agrega al final, sin pisar lo anterior
    filas = [fila('comentarios_generales', 'aca empece el desbrote', etapa='Labores'), fila('desbrote', 'No')]
    with tempfile.TemporaryDirectory() as d:
        pend = os.path.join(d, 'pend.csv')
        _, inf = correr(filas)
        g = pc.exportar_pendientes(inf, pend)
        g['decision'] = 'reemplazar'
        g.to_csv(pend, index=False)
        res, _ = correr(filas, decisiones=pend)
        nota = res[res['nota'].fillna('').str.startswith(pc.PREFIJO_NOTA)].iloc[0]['nota']
        assert nota == "Recuperado de comentario [L01] (comentario en etapa 'Labores') | decisión manual: reemplazar | reemplaza 'No'"


def test_reemplazar_registra_en_la_nota_los_valores_borrados():
    # "reemplazar" borra todos los valores de la variable en el ensayo: la nota deja constancia de cuáles
    filas = [fila('comentarios_generales', 'aparecio arañuela'),
             fila('sanidad_observada', AMARILLAS), fila('sanidad_observada', POLVILLO)]
    with tempfile.TemporaryDirectory() as d:
        pend = os.path.join(d, 'pend.csv')
        _, inf = correr(filas)
        g = pc.exportar_pendientes(inf, pend)
        g['decision'] = 'reemplazar'
        g.to_csv(pend, index=False)
        res, _ = correr(filas, decisiones=pend)
        assert valores(res, 'sanidad_observada') == [CHICOS]
        nota = res[res['nota'].fillna('').str.startswith(pc.PREFIJO_NOTA)].iloc[0]['nota']
        assert nota.endswith(f"| decisión manual: reemplazar | reemplaza '{AMARILLAS}', '{POLVILLO}'"), nota


def test_correccion_no_se_aplica_sola():
    _, inf = correr([fila('comentarios_generales', 'En realidad hubo arañuela'), fila('tutorado', 'Sí')])
    assert inf['estado'].tolist() == ['REVISAR_CORRECCION']


def test_decisiones_y_rescate():
    filas = [fila('comentarios_generales', 'aca empece el desbrote'), fila('desbrote', 'No'),
             fila('comentarios_generales', 'aparecio arañuela', id_participante='P2'),
             fila('sanidad_observada', AMARILLAS, id_participante='P2')]
    with tempfile.TemporaryDirectory() as d:
        pend, dec = os.path.join(d, 'pend.csv'), os.path.join(d, 'dec.csv')
        _, inf = correr(filas)
        g = pc.exportar_pendientes(inf, pend, archivo_decisiones=dec)
        assert len(g) == 2
        g['decision'] = g['variable'].map({'desbrote': 'reemplazar', 'sanidad_observada': 'agregar'})
        g.to_csv(pend, index=False)
        # 1) corrida con la lista [archivo persistente, pendientes completados]
        res, inf2 = correr(filas, decisiones=[dec, pend])
        assert set(inf2['estado']) == {'APLICADA_POR_DECISION'}
        assert valores(res, 'desbrote') == ['Sí'] and valores(res, 'sanidad_observada') == sorted([CHICOS, AMARILLAS])
        # 2) al volver a exportar, las decisiones no se pierden: quedan en el archivo persistente
        pc.exportar_pendientes(inf2, pend, archivo_decisiones=dec)
        assert len(pd.read_csv(dec)) == 2
        res3, inf3 = correr(filas, decisiones=[dec, pend])
        assert set(inf3['estado']) == {'APLICADA_POR_DECISION'} and valores(res3, 'desbrote') == ['Sí']
        # 3) "agregar" en una variable de un solo valor que YA tiene valor es un error explícito
        g['decision'] = 'agregar'
        g.to_csv(pend, index=False)
        _, inf4 = correr(filas, decisiones=pend)
        assert 'ERROR_DECISION' in set(inf4['estado'])


def test_ninguno_existente_y_comentario_dice_que_si_hubo():
    filas = [fila('comentarios_generales', 'aparecio arañuela'), fila('sanidad_observada', NINGUNO)]
    with tempfile.TemporaryDirectory() as d:
        pend = os.path.join(d, 'pend.csv')
        # sin decisión no se toca nada: queda pendiente (sugiere reemplazar)
        res, inf = correr(filas)
        assert valores(res, 'sanidad_observada') == [NINGUNO]
        g = pc.exportar_pendientes(inf, pend)
        assert g['estado'].tolist() == ['REVISAR_CONFLICTO'] and g['accion_sugerida'].tolist() == ['reemplazar']
        for dec, esperado in (('reemplazar', [CHICOS]), ('agregar', [CHICOS]), ('ignorar', [NINGUNO])):
            g['decision'] = dec
            g.to_csv(pend, index=False)
            res, _ = correr(filas, decisiones=pend)
            assert valores(res, 'sanidad_observada') == esperado, dec     # "agregar" también saca el "ninguno"
    # lo inverso: "agregar ninguno" arriba de valores concretos es un error explícito
    filas = [fila('comentarios_generales', 'no hubo plagas'), fila('sanidad_observada', AMARILLAS)]
    with tempfile.TemporaryDirectory() as d:
        pend = os.path.join(d, 'pend.csv')
        _, inf = correr(filas)
        g = pc.exportar_pendientes(inf, pend)
        g['decision'] = 'agregar'
        g.to_csv(pend, index=False)
        _, inf2 = correr(filas, decisiones=pend)
        assert inf2['estado'].tolist() == ['ERROR_DECISION']


def test_dos_comentarios_mismo_ensayo_mismo_valor():
    # uno es claro (se aplica solo) y el otro menciona "variedades": el segundo no debe quedar pendiente
    filas = [fila('comentarios_generales', 'tuvo arañuela roja', etapa='Labores'),
             fila('comentarios_generales', 'principio de arañuela, no como las otras variedades', etapa='Crecimiento y desarrollo'),
             fila('tutorado', 'Sí')]
    res, inf = correr(filas)
    assert sorted(inf['estado']) == ['AUTO_APLICADA', 'REDUNDANTE']
    assert valores(res, 'sanidad_observada') == [CHICOS]          # una sola fila, sin duplicar
    # sin el comentario claro, el de "variedades" sí queda para revisar
    _, inf = correr(filas[1:])
    assert inf['estado'].tolist() == ['REVISAR_ALCANCE']


def test_decisiones_mal_leidas_no_se_ignoran_en_silencio():
    import warnings
    filas = [fila('comentarios_generales', 'aca empece el desbrote'), fila('desbrote', 'No')]
    with tempfile.TemporaryDirectory() as d:
        pend = os.path.join(d, 'pend.csv')
        _, inf = correr(filas)
        g = pc.exportar_pendientes(inf, pend)
        g['decision'] = 'reemplazar'
        # 1) Excel en español: separado por ';' -> se lee igual
        g.to_csv(pend, index=False, sep=';')
        res, inf2 = correr(filas, decisiones=pend)
        assert valores(res, 'desbrote') == ['Sí']
        # 2) archivo sin el encabezado esperado -> error claro, no se ignora
        pd.DataFrame({'x': ['a;b']}).to_csv(pend, index=False)
        try:
            correr(filas, decisiones=pend)
            assert False, 'debía fallar'
        except ValueError as e:
            assert 'columnas esperadas' in str(e)
        # 3) decisión con id que no coincide con nada -> advertencia
        pd.DataFrame({'grupo_id': ['inexistente'], 'propuesta_id': [''], 'decision': ['ignorar']}).to_csv(pend, index=False)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            correr(filas, decisiones=pend)
        assert any('NO se aplicaron' in str(x.message) for x in w)


def test_agregar_en_variable_simple_sin_valor_previo_es_valido():
    # el script SUGIERE "agregar" cuando no hay nada cargado: esa decisión no puede dar error
    reglas = REGLAS.copy()
    reglas.loc[reglas.regla_id == 'L01', 'valor_si_negado'] = ''          # sin "valor si negado": la negación queda para revisar
    df = pd.DataFrame([fila('comentarios_generales', 'sin desbrote'), fila('tutorado', 'Sí')] + CATALOGO)
    _, inf = pc.procesar_comentarios(df, reglas)
    assert inf['estado'].tolist() == ['REVISAR_NEGADO'] and inf['accion_sugerida'].tolist() == ['agregar']
    with tempfile.TemporaryDirectory() as d:
        pend = os.path.join(d, 'pend.csv')
        g = pc.exportar_pendientes(inf, pend)
        g['decision'] = 'agregar'
        g.to_csv(pend, index=False)
        res, inf2 = pc.procesar_comentarios(df, reglas, decisiones=pend)
        assert inf2['estado'].tolist() == ['APLICADA_POR_DECISION'] and valores(res, 'desbrote') == ['Sí']


def test_encabezado_repetido_en_el_csv_se_ignora():
    filas = [fila('comentarios_generales', 'aca empece el desbrote'), fila('desbrote', 'No')]
    with tempfile.TemporaryDirectory() as d:
        pend, dec = os.path.join(d, 'pend.csv'), os.path.join(d, 'dec.csv')
        _, inf = correr(filas)
        g = pc.exportar_pendientes(inf, pend)
        g['decision'] = 'reemplazar'
        # simula pegar filas con su encabezado en el medio del archivo
        con_encabezado = pd.concat([g, pd.DataFrame([{c: c for c in g.columns}]), g], ignore_index=True)
        con_encabezado.to_csv(pend, index=False)
        res, inf2 = correr(filas, decisiones=pend)
        assert valores(res, 'desbrote') == ['Sí']
        pc.exportar_pendientes(inf2, pend, archivo_decisiones=dec)
        assert 'grupo_id' not in set(pd.read_csv(dec)['grupo_id'])


def test_archivo_de_decisiones_inexistente_avisa():
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        correr([fila('comentarios_generales', 'aparecio arañuela'), fila('tutorado', 'Sí')], decisiones='no_existe.csv')
    assert any('No se encontró' in str(x.message) for x in w)


def test_idempotente_y_auditoria():
    filas = [fila('comentarios_generales', 'aparecio arañuela'), fila('tutorado', 'Sí')]
    df = pd.DataFrame(filas + CATALOGO)
    res, inf = pc.procesar_comentarios(df, REGLAS)
    cambios, problemas = pc.auditar_cambios(df, res, verbose=False)
    assert problemas == [] and cambios['filas'].sum() == 1
    res2, inf2 = pc.procesar_comentarios(res, REGLAS)       # correr de nuevo sobre el resultado no cambia nada
    assert len(res2) == len(res) and set(inf2['estado']) == {'REDUNDANTE'}


def test_clave_con_columna_extra_nula_o_distinta():
    """Regresión: con `anio_multiplicacion` nulo (nan != nan) el script no encontraba las respuestas ya cargadas del
    ensayo y marcaba como AUTO_APLICADA cosas que ya estaban (duplicaba filas). Tiene que dar igual con cualquiera de
    las columnas extra de la clave (anio_multiplicacion nula / Int64, variedad_original de texto) o sin ninguna."""
    ya_cargado = [fila('comentarios_generales', 'aparecio arañuela'), fila('sanidad_observada', CHICOS), fila('tutorado', 'Sí')]
    sin_cargar = [fila('comentarios_generales', 'aparecio arañuela'), fila('tutorado', 'Sí')]

    def variantes(filas):
        df = pd.DataFrame(filas + CATALOGO)
        yield 'anio float nulo', df
        yield 'anio Int64', df.assign(anio_multiplicacion=df['anio_multiplicacion'].astype('Int64'))
        yield 'variedad_original texto', df.rename(columns={'anio_multiplicacion': 'variedad_original'}).assign(variedad_original='Var 1')
        yield 'sin columna extra', df.drop(columns='anio_multiplicacion')

    for nombre, df in variantes(ya_cargado):
        res, inf = pc.procesar_comentarios(df, REGLAS)
        assert inf['estado'].tolist() == ['REDUNDANTE'] and len(res) == len(df), nombre
    for nombre, df in variantes(sin_cargar):
        res, inf = pc.procesar_comentarios(df, REGLAS)
        assert inf['estado'].tolist() == ['AUTO_APLICADA'] and len(res) == len(df) + 1, nombre
        assert (res.dtypes == df.dtypes).all(), nombre                 # las columnas no cambian de tipo
        _, problemas = pc.auditar_cambios(df, res, verbose=False)
        assert problemas == [], (nombre, problemas)


# ----------------------------------------------------------------------------
# Pruebas con las reglas REALES (reglas_comentarios.csv)
# ----------------------------------------------------------------------------
RUTA_REGLAS = os.path.join(AQUI, 'reglas_comentarios.csv')
RUTAS_DATASET = [os.path.join(AQUI, 'observaciones_agronomicas_limpio.csv'),
                 os.path.join(AQUI, '..', 'data', 'processed', 'observaciones_agronomicas_limpio.csv')]


def correr_real(texto, etapa='Crecimiento y desarrollo'):
    """Un solo comentario contra las reglas reales. El catálogo = todos los valores que las reglas pueden proponer."""
    reglas = pd.read_csv(RUTA_REGLAS, dtype=str, keep_default_na=False)
    catalogo = [fila(r.variable, r.valor, id_participante='CAT') for r in reglas.drop_duplicates(['variable', 'valor']).itertuples()]
    df = pd.DataFrame([fila('comentarios_generales', texto, etapa=etapa)] + catalogo)
    _, inf = pc.procesar_comentarios(df, RUTA_REGLAS)
    return inf


def aplicadas(texto, variable='sanidad_observada'):
    inf = correr_real(texto)
    return set(inf[(inf['estado'] == 'AUTO_APLICADA') & (inf['variable'] == variable)]['valor_propuesto'])


def test_reales_nombre_solo_no_agrega_mordidas_de_hojas():
    # gusanos / orugas / babosas... solos => "Bichos grandes"; "Hojas con caminitos, agujeros o mordidas" NO
    for txt in ('Aparecieron orugas en el cultivo', 'Hay babosas y caracoles', 'Tuvimos gusanos', 'Langostas en enero',
                'Había una oruga en el jardín vecino'):
        assert aplicadas(txt) == {GRANDES}, txt


def test_reales_mordidas_solo_si_el_comentario_dice_que_mordieron():
    for txt in ('Las orugas se comieron las hojas', 'Los caracoles se comieron las hojas',        # singular y plural
                'Las babosas dejaron agujeros en las hojas', 'Hojas mordidas por orugas',        # orden inverso
                'Hubo orugas que hicieron mucho daño'):
        assert aplicadas(txt) == {GRANDES, MORDIDAS}, txt
    # el verbo de daño tiene que estar en la misma oración y sin negación en el medio
    for txt in ('Las orugas no comieron las hojas', 'Orugas, nada de daño en las hojas',
                'Aparecieron orugas. Se comieron las hojas', 'Había orugas y dejé un comentario en la planilla'):
        assert aplicadas(txt) == {GRANDES}, txt


def test_reales_herbivoros_por_nombre():
    for txt in ('Vi una liebre en la huerta', 'Los pájaros picotearon los frutos', 'Se perdieron frutos por ataque de cuyes'):
        assert aplicadas(txt) == {HERB}, txt
    assert aplicadas('Usé mantas antipájaros') == set()


def test_reales_creencias_no_se_aplican():
    creencias = [
        'Creo que fue una oruga', 'Creemos que eran pulgones', 'Creía que eran pulgones', 'Pienso que fueron pulgones',
        'Pudo haber sido una oruga', 'Pueden haber sido cuyes', 'Deben haber sido las orugas', 'Debe haber sido una liebre',
        'Habrán sido las orugas', 'Habría sido una liebre', 'Podría ser arañuela', 'Quizá una oruga mordió las hojas',
        'Tal vez fue una liebre', 'Seguramente eran pulgones', 'Posiblemente fueron cuyes', 'Supongo que eran chinches',
        'Presumo que fue una vizcacha', 'Sospecho de las babosas', 'Intuyo que son hormigas', 'Diría que fueron cuyes',
        'Parece que la liebre se comió los frutos', 'Me da la sensación de que eran chinches',
        'Tengo la impresión de que fue una liebre', 'No sabría decir si eran pulgones', 'No sé si fue una liebre',
        'No tengo certeza, pero había orugas', 'Si no me equivoco eran pulgones', 'Las orugas, creo, comieron las hojas',
        '¿Serán pulgones?',
    ]
    for txt in creencias:
        inf = correr_real(txt)
        assert len(inf) and set(inf['estado']) == {'DESCARTADA_INCIERTA'}, (txt, inf['estado'].tolist())


def test_reales_afirmaciones_si_se_aplican():
    assert aplicadas('Tuvimos pulgones en febrero') == {CHICOS}
    assert aplicadas('Con certeza fueron orugas') == {GRANDES}
    assert aplicadas('Había una liebre que se comía las hojas') == {HERB}
    assert aplicadas('Aparecieron chinches y oídio') == {CHICOS, POLVILLO}


def test_reales_ninguna_plaga_no_propone_nada_en_sanidad():
    # "no hubo plagas" NO equivale a "no se observó ningún problema": no se propone ninguna fila
    for txt in ('No hubo plagas en todo el ciclo', 'Sin plagas', 'Libre de plagas'):
        inf = correr_real(txt)
        assert inf[inf['variable'] == 'sanidad_observada'].empty, txt


def test_reales_lixiviado_de_humus_no_es_aplicar_humus():
    # un lixiviado / té / purín ES un abono líquido, aunque se haga a partir de compost o humus
    liquidos = 'Abonos líquidos o biopreparados'
    solidos = 'Compost, lombricompuesto, humus o bokashi'
    for txt in ('Fertilizacion con lixiviado de humus', 'Apliqué lixiviado de lombricompuesto cada semana', 'Hice té de compost y lo apliqué'):
        assert aplicadas(txt, 'fertilizacion') == {liquidos}, txt
    # pero si además aplicó el sólido, sí van los dos
    assert aplicadas('Eché compost y regué con lixiviado', 'fertilizacion') == {solidos, liquidos}
    assert aplicadas('Apliqué humus de lombriz en cada planta', 'fertilizacion') == {solidos}


def test_reales_valores_nuevos_de_riego_y_conduccion():
    assert aplicadas('Regamos por aspersión todas las mañanas', 'riego') == {'Aspersión / microaspersión'}
    assert aplicadas('Se regó con manguera', 'riego') == {'Manual con regadera o manguera'}
    assert aplicadas('Hicimos aspersión de jabón potásico contra la arañuela', 'riego') == set()   # eso no es riego
    assert aplicadas('Las plantas se condujeron a un solo tallo', 'conduccion') == {'A un tallo'}
    assert aplicadas('Conduje a dos tallos', 'conduccion') == {'A dos tallos'}


def test_reales_reglas_validas_y_valores_en_el_dataset():
    reglas = pc.cargar_reglas(RUTA_REGLAS)                      # compila todos los patrones y revisa ids repetidos
    assert len(reglas) > 0
    ruta = next((r for r in RUTAS_DATASET if os.path.exists(r)), None)
    if ruta is None:
        print('   (se saltea la comparación con el dataset: no está observaciones_agronomicas_limpio.csv al lado)')
        return
    df = pd.read_csv(ruta, usecols=['variable', 'valor'], dtype=str)
    catalogo = df.groupby('variable')['valor'].agg(set).to_dict()
    # categorías que existen en el diseño pero todavía no aparecen en ningún dato (por eso se descartan como "fuera de catálogo")
    todavia_sin_datos = {('sanidad_observada', MORDIDAS), ('sanidad_observada', 'Manchas en hojas o tallos')}
    for r in reglas:
        ok = r['valor'] in catalogo.get(r['variable'], set()) or (r['variable'], r['valor']) in todavia_sin_datos
        assert ok, f"{r['regla_id']}: '{r['valor']}' no existe en {r['variable']} (¿se renombró el valor en el notebook?)"


if __name__ == '__main__':
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in pruebas:
        if t.__name__.startswith('test_reales_') and not os.path.exists(RUTA_REGLAS):
            print('skip', t.__name__, '(no está reglas_comentarios.csv al lado)')
            continue
        t()
        print('ok ', t.__name__)
    print(f'{len(pruebas)} pruebas OK')
