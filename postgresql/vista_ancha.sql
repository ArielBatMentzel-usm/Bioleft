-- v_ensayos_ancho: 1 fila por ensayo, formato ancho. Es lo único que lee app.py.
-- Ajustada al DER (crear_tablas_completo.sql). Control: SELECT count(*) FROM v_ensayos_ancho;  -- = filas de ensayos
-- Variables multivalor: texto unido con ' | ' (string_agg sobre cat_*.valor); el app lo separa en pandas.
-- Cantidades de plantines: mismo nombre en maceta y suelo en la base, acá llevan sufijo para no chocar.

CREATE OR REPLACE VIEW v_ensayos_ancho AS
SELECT
  e.ensayo_id,
  e.campana,
  s.participante_id AS id_participante,
  e.sitio_id        AS id_sitio,
  p.nombre          AS provincia,
  ci.nombre         AS localidad,
  e.variedad_id,
  v.nombre_variedad,
  e.anio_multiplicacion,
  e.lote_semillas,
  si.metodo_siembra,
  si.fecha_siembra,
  si.cantidad_semillas_sembradas,
  si.fecha_emergencia,
  si.cantidad_plantulas_emergidas,
  tm.ubicacion_contenedor,
  tm.profundidad_contenedor_cm,
  tm.fecha_trasplante_maceta,
  tm.cantidad_plantines_trasplantados AS cantidad_plantines_trasplantados_maceta,
  tm.cantidad_plantines_implantados AS cantidad_plantines_implantados_maceta,
  ts.ubicacion_parcela,
  ts.superficie_parcela_m2,
  ts.fecha_trasplante_suelo,
  ts.densidad_plantas_m2,
  ts.cantidad_plantines_trasplantados AS cantidad_plantines_trasplantados_suelo,
  ts.cantidad_plantines_implantados AS cantidad_plantines_implantados_suelo,
  lab.desbrote,
  lab.tutorado,
  lab.conduccion,
  lab.riego,
  cr.fecha_primera_floracion,
  cr.tolerancia_estres_hidrico,
  cr.tolerancia_quemadura_sol,
  cr.sanidad,
  cr.uniformidad,
  cr.cantidad_plantas_muertas,
  lf.raleo_frutos,
  lf.eliminacion_brote_apical,
  cp.cantidad_plantas_cosechadas,
  cp.color_fruto_cosecha,
  cp.cantidad_frutos_muestra_poscosecha,
  cp.duracion_poscosecha_dias,
  cp.condicion_poscosecha,
  cp.fecha_primera_cosecha,
  cp.fecha_ultima_cosecha,
  cp.peso_total_cosechado_kg,
  cp.total_frutos_cosechados,
  d.gusto_general,
  d.dulce_marcado,
  d.dulce_intensidad,
  d.acido_marcado,
  d.acido_intensidad,
  d.jugoso_marcado,
  d.jugoso_intensidad,
  d.persistente_marcado,
  d.persistente_intensidad,
  d.olor_tomate_maduro_marcado,
  d.olor_tomate_maduro_intensidad,
  d.olor_tomate_verde_marcado,
  d.olor_tomate_verde_intensidad,
  d.mucha_pulpa_marcado,
  d.mucha_pulpa_intensidad,
  d.poca_pulpa_marcado,
  d.poca_pulpa_intensidad,
  d.pulpa_dura_marcado,
  d.pulpa_dura_intensidad,
  d.pulpa_blanda_marcado,
  d.pulpa_blanda_intensidad,
  d.mucha_semilla_marcado,
  d.mucha_semilla_intensidad,
  d.poca_semilla_marcado,
  d.poca_semilla_intensidad,
  d.aguachento_marcado,
  d.aguachento_intensidad,
  d.pastoso_marcado,
  d.pastoso_intensidad,
  d.piel_dura_marcado,
  d.piel_dura_intensidad,
  mv_sustrato.sustrato,
  mv_cultivo_asociado_maceta.cultivo_asociado_maceta,
  mv_cultivo_asociado_suelo.cultivo_asociado_suelo,
  mv_fertilizacion.fertilizacion,
  mv_control_plagas.control_plagas,
  mv_control_malezas.control_malezas,
  mv_cobertura_suelo.cobertura_suelo,
  mv_sanidad_observada.sanidad_observada,
  mv_causa_desuniformidad.causa_desuniformidad,
  mv_causa_muerte_plantas.causa_muerte_plantas
FROM ensayos e
LEFT JOIN sitios s      ON s.sitio_id = e.sitio_id
LEFT JOIN provincias p  ON p.provincia_id = s.provincia_id
LEFT JOIN ciudades ci   ON ci.ciudad_id = s.ciudad_id
LEFT JOIN variedades v  ON v.variedad_id = e.variedad_id
LEFT JOIN siembra si ON si.ensayo_id = e.ensayo_id
LEFT JOIN trasplante_maceta tm ON tm.ensayo_id = e.ensayo_id
LEFT JOIN trasplante_suelo ts ON ts.ensayo_id = e.ensayo_id
LEFT JOIN labores lab ON lab.ensayo_id = e.ensayo_id
LEFT JOIN crecimiento cr ON cr.ensayo_id = e.ensayo_id
LEFT JOIN labores_fructificacion lf ON lf.ensayo_id = e.ensayo_id
LEFT JOIN cosecha_poscosecha cp ON cp.ensayo_id = e.ensayo_id
LEFT JOIN degustacion d ON d.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS sustrato
  FROM sustrato x JOIN cat_sustrato c USING (sustrato_id)
  GROUP BY x.ensayo_id
) mv_sustrato ON mv_sustrato.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS cultivo_asociado_maceta
  FROM cultivo_asociado_maceta x JOIN cat_cultivo_asociado c USING (cultivo_asociado_id)
  GROUP BY x.ensayo_id
) mv_cultivo_asociado_maceta ON mv_cultivo_asociado_maceta.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS cultivo_asociado_suelo
  FROM cultivo_asociado_suelo x JOIN cat_cultivo_asociado c USING (cultivo_asociado_id)
  GROUP BY x.ensayo_id
) mv_cultivo_asociado_suelo ON mv_cultivo_asociado_suelo.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS fertilizacion
  FROM fertilizacion x JOIN cat_fertilizacion c USING (fertilizacion_id)
  GROUP BY x.ensayo_id
) mv_fertilizacion ON mv_fertilizacion.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS control_plagas
  FROM control_plagas x JOIN cat_control_plagas c USING (control_plagas_id)
  GROUP BY x.ensayo_id
) mv_control_plagas ON mv_control_plagas.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS control_malezas
  FROM control_malezas x JOIN cat_control_malezas c USING (control_malezas_id)
  GROUP BY x.ensayo_id
) mv_control_malezas ON mv_control_malezas.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS cobertura_suelo
  FROM cobertura_suelo x JOIN cat_cobertura_suelo c USING (cobertura_suelo_id)
  GROUP BY x.ensayo_id
) mv_cobertura_suelo ON mv_cobertura_suelo.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS sanidad_observada
  FROM sanidad_observada x JOIN cat_sanidad_observada c USING (sanidad_observada_id)
  GROUP BY x.ensayo_id
) mv_sanidad_observada ON mv_sanidad_observada.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS causa_desuniformidad
  FROM causa_desuniformidad x JOIN cat_causa_desuniformidad c USING (causa_desuniformidad_id)
  GROUP BY x.ensayo_id
) mv_causa_desuniformidad ON mv_causa_desuniformidad.ensayo_id = e.ensayo_id
LEFT JOIN (
  SELECT x.ensayo_id, string_agg(c.valor, ' | ' ORDER BY c.valor) AS causa_muerte_plantas
  FROM causa_muerte_plantas x JOIN cat_causa_muerte_plantas c USING (causa_muerte_plantas_id)
  GROUP BY x.ensayo_id
) mv_causa_muerte_plantas ON mv_causa_muerte_plantas.ensayo_id = e.ensayo_id;
