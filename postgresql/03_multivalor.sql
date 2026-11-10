-- 03_multivalor.sql: Intermedias de variables multivalor (requiere 01 y 02)

CREATE TABLE "sustrato" (
  "ensayo_id" BIGINT NOT NULL,
  "sustrato_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "sustrato_id")
);

CREATE TABLE "cultivo_asociado_maceta" (
  "ensayo_id" BIGINT NOT NULL,
  "cultivo_asociado_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "cultivo_asociado_id")
);

CREATE TABLE "cultivo_asociado_suelo" (
  "ensayo_id" BIGINT NOT NULL,
  "cultivo_asociado_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "cultivo_asociado_id")
);

CREATE TABLE "fertilizacion" (
  "ensayo_id" BIGINT NOT NULL,
  "fertilizacion_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "fertilizacion_id")
);

CREATE TABLE "control_plagas" (
  "ensayo_id" BIGINT NOT NULL,
  "control_plagas_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "control_plagas_id")
);

CREATE TABLE "causa_desuniformidad" (
  "ensayo_id" BIGINT NOT NULL,
  "causa_desuniformidad_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "causa_desuniformidad_id")
);

CREATE TABLE "sanidad_observada" (
  "ensayo_id" BIGINT NOT NULL,
  "sanidad_observada_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "sanidad_observada_id")
);

CREATE TABLE "causa_muerte_plantas" (
  "ensayo_id" BIGINT NOT NULL,
  "causa_muerte_plantas_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "causa_muerte_plantas_id")
);

CREATE TABLE "control_malezas" (
  "ensayo_id" BIGINT NOT NULL,
  "control_malezas_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "control_malezas_id")
);

CREATE TABLE "cobertura_suelo" (
  "ensayo_id" BIGINT NOT NULL,
  "cobertura_suelo_id" INTEGER NOT NULL,
  PRIMARY KEY ("ensayo_id", "cobertura_suelo_id")
);

CREATE INDEX "idx_ensayo_sustrato_sustrato" ON "sustrato" ("sustrato_id");
CREATE INDEX "idx_ensayo_cultivo_asociado_maceta_cultivo_asociado" ON "cultivo_asociado_maceta" ("cultivo_asociado_id");
CREATE INDEX "idx_ensayo_cultivo_asociado_suelo_cultivo_asociado" ON "cultivo_asociado_suelo" ("cultivo_asociado_id");
CREATE INDEX "idx_ensayo_fertilizacion_fertilizacion" ON "fertilizacion" ("fertilizacion_id");
CREATE INDEX "idx_ensayo_control_plagas_control_plagas" ON "control_plagas" ("control_plagas_id");
CREATE INDEX "idx_ensayo_causa_desuniformidad_causa_desuniformidad" ON "causa_desuniformidad" ("causa_desuniformidad_id");
CREATE INDEX "idx_ensayo_sanidad_observada_sanidad_observada" ON "sanidad_observada" ("sanidad_observada_id");
CREATE INDEX "idx_ensayo_causa_muerte_plantas_causa_muerte_plantas" ON "causa_muerte_plantas" ("causa_muerte_plantas_id");
CREATE INDEX "idx_ensayo_control_malezas_control_malezas" ON "control_malezas" ("control_malezas_id");
CREATE INDEX "idx_ensayo_cobertura_suelo_cobertura_suelo" ON "cobertura_suelo" ("cobertura_suelo_id");

ALTER TABLE "sustrato" ADD FOREIGN KEY ("ensayo_id") REFERENCES "trasplante_maceta" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "sustrato" ADD FOREIGN KEY ("sustrato_id") REFERENCES "cat_sustrato" ("sustrato_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "cultivo_asociado_maceta" ADD FOREIGN KEY ("ensayo_id") REFERENCES "trasplante_maceta" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "cultivo_asociado_maceta" ADD FOREIGN KEY ("cultivo_asociado_id") REFERENCES "cat_cultivo_asociado" ("cultivo_asociado_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "cultivo_asociado_suelo" ADD FOREIGN KEY ("ensayo_id") REFERENCES "trasplante_suelo" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "cultivo_asociado_suelo" ADD FOREIGN KEY ("cultivo_asociado_id") REFERENCES "cat_cultivo_asociado" ("cultivo_asociado_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "fertilizacion" ADD FOREIGN KEY ("ensayo_id") REFERENCES "labores" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "fertilizacion" ADD FOREIGN KEY ("fertilizacion_id") REFERENCES "cat_fertilizacion" ("fertilizacion_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "control_plagas" ADD FOREIGN KEY ("ensayo_id") REFERENCES "labores" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "control_plagas" ADD FOREIGN KEY ("control_plagas_id") REFERENCES "cat_control_plagas" ("control_plagas_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "causa_desuniformidad" ADD FOREIGN KEY ("ensayo_id") REFERENCES "crecimiento" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "causa_desuniformidad" ADD FOREIGN KEY ("causa_desuniformidad_id") REFERENCES "cat_causa_desuniformidad" ("causa_desuniformidad_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "sanidad_observada" ADD FOREIGN KEY ("ensayo_id") REFERENCES "crecimiento" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "sanidad_observada" ADD FOREIGN KEY ("sanidad_observada_id") REFERENCES "cat_sanidad_observada" ("sanidad_observada_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "causa_muerte_plantas" ADD FOREIGN KEY ("ensayo_id") REFERENCES "crecimiento" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "causa_muerte_plantas" ADD FOREIGN KEY ("causa_muerte_plantas_id") REFERENCES "cat_causa_muerte_plantas" ("causa_muerte_plantas_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "control_malezas" ADD FOREIGN KEY ("ensayo_id") REFERENCES "labores" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "control_malezas" ADD FOREIGN KEY ("control_malezas_id") REFERENCES "cat_control_malezas" ("control_malezas_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "cobertura_suelo" ADD FOREIGN KEY ("ensayo_id") REFERENCES "trasplante_suelo" ("ensayo_id") ON DELETE CASCADE ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE "cobertura_suelo" ADD FOREIGN KEY ("cobertura_suelo_id") REFERENCES "cat_cobertura_suelo" ("cobertura_suelo_id") ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
