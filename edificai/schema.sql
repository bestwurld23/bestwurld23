-- edificAI-style GIS analytics backend — PostGIS schema
-- Target: PostgreSQL 16+ / PostGIS 3.4+
--
-- CRS strategy:
--   32632 (WGS84 / UTM 32N) is canonical — Lombardy regional data ships in it,
--   and metres make area filters and ST_Area honest.
--   3857 is a generated column, because MVT tiles need web mercator.
--   Both generated columns rely on ST_Transform/ST_Area being IMMUTABLE. If your
--   PostGIS build rejects them, drop GENERATED and fill via a BEFORE INSERT/UPDATE trigger.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- municipality name autocomplete

CREATE SCHEMA IF NOT EXISTS ref;         -- administrative reference data
CREATE SCHEMA IF NOT EXISTS planning;    -- PGT perimeters
CREATE SCHEMA IF NOT EXISTS cadastre;    -- catasto parcels
CREATE SCHEMA IF NOT EXISTS energy;      -- APE / CENED
CREATE SCHEMA IF NOT EXISTS app;         -- user-facing state (saved selections, exports)
CREATE SCHEMA IF NOT EXISTS meta;        -- load provenance

-- ---------------------------------------------------------------------------
-- meta: every row in every table traces back to one dataset load
-- ---------------------------------------------------------------------------
CREATE TABLE meta.dataset_load (
    load_id        bigserial PRIMARY KEY,
    dataset_key    text        NOT NULL,          -- e.g. 'pgt_previsioni', 'catasto_mi', 'cened2'
    source_url     text        NOT NULL,
    license        text        NOT NULL,          -- 'CC-BY-4.0', 'CC0-1.0', ...
    attribution    text,                          -- the exact string the license obliges you to show
    source_updated date,                          -- publisher's own "last updated"
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    row_count      bigint,
    notes          text
);

-- ---------------------------------------------------------------------------
-- ref: 12 provinces, 1501 municipalities
-- ---------------------------------------------------------------------------
CREATE TABLE ref.province (
    cod_prov   char(3) PRIMARY KEY,               -- ISTAT province code, zero-padded
    sigla      char(2) NOT NULL UNIQUE,           -- MI, BG, BS, ...
    nome       text    NOT NULL,
    geom       geometry(MultiPolygon, 32632) NOT NULL,
    load_id    bigint REFERENCES meta.dataset_load
);

CREATE TABLE ref.comune (
    cod_istat  char(6) PRIMARY KEY,               -- ISTAT municipality code (the universal join key)
    cod_prov   char(3) NOT NULL REFERENCES ref.province,
    nome       text    NOT NULL,
    popolazione integer,
    geom       geometry(MultiPolygon, 32632) NOT NULL,
    geom_3857  geometry(MultiPolygon, 3857)
               GENERATED ALWAYS AS (ST_Transform(geom, 3857)) STORED,
    area_mq    numeric GENERATED ALWAYS AS (ST_Area(geom)) STORED,
    load_id    bigint REFERENCES meta.dataset_load
);
CREATE INDEX comune_geom_gix   ON ref.comune USING GIST (geom);
CREATE INDEX comune_geom_3857_gix ON ref.comune USING GIST (geom_3857);
CREATE INDEX comune_nome_trgm  ON ref.comune USING GIN (nome gin_trgm_ops);
CREATE INDEX comune_prov_idx   ON ref.comune (cod_prov);

-- ---------------------------------------------------------------------------
-- planning: the ~23k perimeters. One table, one discriminator — not three tables.
-- Source schemas differ per category, so category-specific fields live in attrs.
-- ---------------------------------------------------------------------------
CREATE TYPE planning.category AS ENUM (
    'trasformazione',       -- ambiti di trasformazione (PGT Documento di Piano)
    'rigenerazione',        -- art. 8-bis l.r. 12/2005
    'dismessa_degradata'    -- art. 40-bis l.r. 12/2005
);

CREATE TABLE planning.perimeter (
    perimeter_id  bigserial PRIMARY KEY,
    category      planning.category NOT NULL,
    cod_istat     char(6) NOT NULL REFERENCES ref.comune,
    source_id     text    NOT NULL,               -- publisher's own identifier
    denominazione text,
    destinazione  text,                           -- intended use, normalised
    destinazione_raw text,                        -- as published, kept for audit
    strumento     text,                           -- PGT / variante, delibera reference
    data_adozione date,
    doc_url       text,                           -- link to the official fact sheet
    attrs         jsonb NOT NULL DEFAULT '{}',    -- everything category-specific
    geom          geometry(MultiPolygon, 32632) NOT NULL,
    geom_3857     geometry(MultiPolygon, 3857)
                  GENERATED ALWAYS AS (ST_Transform(geom, 3857)) STORED,
    area_mq       numeric GENERATED ALWAYS AS (ST_Area(geom)) STORED,
    load_id       bigint REFERENCES meta.dataset_load,
    UNIQUE (category, source_id, load_id)
);

CREATE INDEX perimeter_geom_gix      ON planning.perimeter USING GIST (geom);
CREATE INDEX perimeter_geom_3857_gix ON planning.perimeter USING GIST (geom_3857);
-- The filter panel's hot path: category + area range, inside a viewport.
CREATE INDEX perimeter_cat_area_idx  ON planning.perimeter (category, area_mq);
CREATE INDEX perimeter_comune_idx    ON planning.perimeter (cod_istat);
CREATE INDEX perimeter_attrs_gin     ON planning.perimeter USING GIN (attrs jsonb_path_ops);

-- Low-zoom companion table. Do NOT simplify inside the tile function at z<11:
-- that re-simplifies the same geometry on every tile request.
CREATE MATERIALIZED VIEW planning.perimeter_generalised AS
SELECT perimeter_id, category, cod_istat, area_mq,
       ST_SimplifyPreserveTopology(geom_3857, 25) AS geom_3857
FROM   planning.perimeter;
CREATE INDEX perimeter_gen_gix ON planning.perimeter_generalised USING GIST (geom_3857);
CREATE INDEX perimeter_gen_cat_idx ON planning.perimeter_generalised (category, area_mq);

-- ---------------------------------------------------------------------------
-- cadastre: millions of parcels. LIST-partitioned by province so a
-- province-scoped query touches one partition, and a reload swaps one partition.
-- Field names follow the INSPIRE CadastralParcel delivery from Agenzia Entrate.
-- ---------------------------------------------------------------------------
CREATE TABLE cadastre.parcel (
    parcel_id     bigserial,
    cod_prov      char(3) NOT NULL,
    cod_istat     char(6) NOT NULL,
    -- INSPIRE national cadastral reference, e.g. 'E801A_0012A.00045'
    nat_cad_ref   text    NOT NULL,
    sezione       text,
    foglio        text,
    particella    text,
    geom          geometry(MultiPolygon, 32632) NOT NULL,
    geom_3857     geometry(MultiPolygon, 3857)
                  GENERATED ALWAYS AS (ST_Transform(geom, 3857)) STORED,
    area_mq       numeric GENERATED ALWAYS AS (ST_Area(geom)) STORED,
    load_id       bigint,
    PRIMARY KEY (cod_prov, parcel_id)
) PARTITION BY LIST (cod_prov);

-- One partition per Lombardy province (ISTAT codes).
DO $$
DECLARE p text;
BEGIN
  FOREACH p IN ARRAY ARRAY['012','013','014','015','016','017','018','019','020','097','098','108']
  LOOP
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS cadastre.parcel_%1$s PARTITION OF cadastre.parcel FOR VALUES IN (%2$L)',
      p, p);
    EXECUTE format('CREATE INDEX IF NOT EXISTS parcel_%1$s_gix ON cadastre.parcel_%1$s USING GIST (geom_3857)', p);
    EXECUTE format('CREATE INDEX IF NOT EXISTS parcel_%1$s_ref ON cadastre.parcel_%1$s (nat_cad_ref)', p);
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- energy: CENED+2 certificate rows, plus the per-municipality rollup the KPI
-- cards actually read. Certificates carry no public geometry — they join on
-- cod_istat only, which caps spatial resolution at municipality level. Say so
-- in the UI rather than implying building-level precision.
-- ---------------------------------------------------------------------------
CREATE TABLE energy.ape (
    ape_id          bigserial PRIMARY KEY,
    cod_istat       char(6) NOT NULL REFERENCES ref.comune,
    anno_emissione  smallint,
    classe          text,          -- A4..G
    ep_gl_nren      numeric,       -- kWh/m2 yr, non-renewable global energy
    destinazione    text,          -- E.1(1) = residential, owner-occupied
    superficie_utile numeric,
    anno_costruzione smallint,
    attrs           jsonb NOT NULL DEFAULT '{}',   -- the long tail of ~198 columns
    load_id         bigint REFERENCES meta.dataset_load
);
CREATE INDEX ape_comune_idx ON energy.ape (cod_istat);
CREATE INDEX ape_comune_dest_idx ON energy.ape (cod_istat, destinazione);
-- 2M+ rows, append-mostly, queried by year range: BRIN is cheap here.
CREATE INDEX ape_anno_brin ON energy.ape USING BRIN (anno_emissione);

-- percentile_cont has no numeric overload: a numeric input comes back as
-- double precision. Cast it back, so energy values don't drift into floats.
CREATE MATERIALIZED VIEW energy.ape_by_comune AS
WITH per_class AS (
    SELECT cod_istat, classe, count(*) AS n
    FROM   energy.ape
    WHERE  classe IS NOT NULL
    GROUP  BY cod_istat, classe
), classi AS (
    SELECT cod_istat, jsonb_object_agg(classe, n) AS classi
    FROM   per_class
    GROUP  BY cod_istat
), totals AS (
    SELECT cod_istat,
           count(*)                                           AS n_ape,
           count(*) FILTER (WHERE destinazione LIKE 'E.1%')    AS n_residenziali,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY ep_gl_nren)::numeric
                                                              AS ep_gl_nren_median,
           avg(superficie_utile)                               AS superficie_media
    FROM   energy.ape
    GROUP  BY cod_istat
)
SELECT t.*, COALESCE(c.classi, '{}'::jsonb) AS classi
FROM   totals t
LEFT   JOIN classi c USING (cod_istat);
CREATE UNIQUE INDEX ape_by_comune_pk ON energy.ape_by_comune (cod_istat);

-- ---------------------------------------------------------------------------
-- app: saved selections and exports
-- ---------------------------------------------------------------------------
CREATE TABLE app.saved_selection (
    selection_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      text        NOT NULL,
    name         text        NOT NULL,
    filters      jsonb       NOT NULL,            -- the filter panel state, replayable
    perimeter_ids bigint[]   NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX saved_selection_user_idx ON app.saved_selection (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Tile functions (Martin signature: z, x, y, query_params json -> bytea).
-- For pg_tileserv, replace query_params with explicit scalar arguments.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION planning.perimeter_mvt(
    z integer, x integer, y integer, query_params json DEFAULT '{}'
) RETURNS bytea AS $$
DECLARE
    env       geometry := ST_TileEnvelope(z, x, y);
    cats      text[]   := CASE WHEN query_params->>'categories' IS NULL THEN NULL
                               ELSE string_to_array(query_params->>'categories', ',') END;
    area_min  numeric  := (query_params->>'area_min')::numeric;
    area_max  numeric  := (query_params->>'area_max')::numeric;
    tile      bytea;
BEGIN
    IF z < 11 THEN
        SELECT ST_AsMVT(t, 'perimeters', 4096, 'geom') INTO tile
        FROM (
            SELECT perimeter_id, category::text, area_mq,
                   ST_AsMVTGeom(g.geom_3857, env, 4096, 64, true) AS geom
            FROM   planning.perimeter_generalised g
            WHERE  g.geom_3857 && env
              AND (cats     IS NULL OR g.category::text = ANY(cats))
              AND (area_min IS NULL OR g.area_mq >= area_min)
              AND (area_max IS NULL OR g.area_mq <= area_max)
        ) t WHERE t.geom IS NOT NULL;
    ELSE
        SELECT ST_AsMVT(t, 'perimeters', 4096, 'geom') INTO tile
        FROM (
            SELECT p.perimeter_id, p.category::text, p.denominazione,
                   p.destinazione, p.area_mq, p.cod_istat,
                   ST_AsMVTGeom(p.geom_3857, env, 4096, 64, true) AS geom
            FROM   planning.perimeter p
            WHERE  p.geom_3857 && env
              AND (cats     IS NULL OR p.category::text = ANY(cats))
              AND (area_min IS NULL OR p.area_mq >= area_min)
              AND (area_max IS NULL OR p.area_mq <= area_max)
        ) t WHERE t.geom IS NOT NULL;
    END IF;
    RETURN COALESCE(tile, ''::bytea);
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

-- Parcels: only ever serve them at high zoom. An unguarded z=8 request for
-- millions of parcels is how this kind of dashboard falls over.
CREATE OR REPLACE FUNCTION cadastre.parcel_mvt(
    z integer, x integer, y integer, query_params json DEFAULT '{}'
) RETURNS bytea AS $$
DECLARE
    env  geometry := ST_TileEnvelope(z, x, y);
    tile bytea;
BEGIN
    IF z < 15 THEN
        RETURN ''::bytea;
    END IF;
    SELECT ST_AsMVT(t, 'parcels', 4096, 'geom') INTO tile
    FROM (
        SELECT p.nat_cad_ref, p.foglio, p.particella, p.area_mq,
               ST_AsMVTGeom(p.geom_3857, env, 4096, 64, true) AS geom
        FROM   cadastre.parcel p
        WHERE  p.geom_3857 && env
    ) t WHERE t.geom IS NOT NULL;
    RETURN COALESCE(tile, ''::bytea);
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

-- ---------------------------------------------------------------------------
-- KPI panel: one round trip, bounded by the viewport.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION planning.kpi_in_bbox(
    minx double precision, miny double precision,
    maxx double precision, maxy double precision,
    cats text[] DEFAULT NULL,
    area_min numeric DEFAULT NULL,
    area_max numeric DEFAULT NULL
) RETURNS jsonb AS $$
    WITH env AS (
        SELECT ST_Transform(ST_MakeEnvelope(minx, miny, maxx, maxy, 4326), 32632) AS g
    ), hit AS (
        SELECT p.category, p.area_mq
        FROM   planning.perimeter p, env e
        WHERE  p.geom && e.g
          AND  ST_Intersects(p.geom, e.g)
          AND (cats     IS NULL OR p.category::text = ANY(cats))
          AND (area_min IS NULL OR p.area_mq >= area_min)
          AND (area_max IS NULL OR p.area_mq <= area_max)
    )
    SELECT jsonb_build_object(
        'count',        count(*),
        'area_mq_tot',  COALESCE(sum(area_mq), 0),
        'area_mq_med',  COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY area_mq)::numeric, 0),
        'by_category',  COALESCE(
            (SELECT jsonb_object_agg(category, n)
             FROM (SELECT category, count(*) AS n FROM hit GROUP BY category) s), '{}'::jsonb)
    ) FROM hit;
$$ LANGUAGE sql STABLE PARALLEL SAFE;
