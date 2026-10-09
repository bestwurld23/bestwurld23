# Sourcing the data (Lombardy)

Status of each link below: **verified by search on 2026-10-09** unless marked otherwise.
I could not reach `geoportale.regione.lombardia.it` directly from this session (DNS is
restricted here), so exact WFS layer names must be copied from each dataset's own
metadata record. The portal paths themselves are confirmed.

## 1. Planning perimeters (~23k) — the core asset

The post's three categories come from two different regimes, and this matters for ETL:

| Category | Legal basis | Where it lives |
|---|---|---|
| Ambiti di trasformazione (~14.1k) | PGT Documento di Piano | Regional PGT geodatabase, "Tavola delle Previsioni" |
| Ambiti di rigenerazione (~3.3k) | art. 8-bis l.r. 12/2005 (as amended by l.r. 18/2019) | Dedicated Geoportale dataset |
| Aree dismesse / degradate (~5.6k) | art. 40-bis l.r. 12/2005 | Municipal resolutions, aggregated regionally |

- **Start here:** [Geoportale della Lombardia — Download Dati](https://www.geoportale.regione.lombardia.it/download-dati)
  and the [catalogue search](https://www.geoportale.regione.lombardia.it/ricerca), which
  can filter by service type including `Servizio WFS`.
- **Regeneration areas:** search the catalogue for *"Ambiti di Rigenerazione art. 8 bis
  l.r. 12/2005"*. The record links a viewer, a download service, and the metadata.
- **Transformation areas:** do **not** go to MISURC. The *Mosaico Informatizzato degli
  Strumenti Urbanistici Comunali* is the pre-PGT mosaic of old PRG plans (1:10,000,
  circa 2002–2008) and its published sections are *destinazioni funzionali, modalità
  attuative, aree vincolate e di rispetto, parchi di PRG* — no transformation or disused
  layer. The Geoportale describes the PGT-era 1:10,000 geodatabase synthesising the
  "Tavola delle Previsioni" as MISURC's natural successor. That is your source.
- **OGC services index:** [Servizi OGC](https://www.geoportale.regione.lombardia.it/servizi-ogc).
  For anything not downloadable, there is a
  [request/consultation procedure](https://www.geoportale.regione.lombardia.it/en-GB/consultazione-e-distribuzione);
  the responsible office is Direzione Generale Territorio e Sistemi Verdi, `sit_rl@regione.lombardia.it`.

Load with GDAL, forcing the canonical CRS:

```bash
ogr2ogr -f PostgreSQL "PG:host=$PGHOST dbname=edificai" \
  -nln planning_stage_rigenerazione -nlt MULTIPOLYGON \
  -t_srs EPSG:32632 -lco GEOMETRY_NAME=geom -lco FID=stage_id \
  -overwrite /data/rigenerazione.gpkg
```

Then project the staging table into `planning.perimeter`, mapping the publisher's
columns into the typed ones and dumping the remainder into `attrs`:

```sql
INSERT INTO planning.perimeter
  (category, cod_istat, source_id, denominazione, destinazione_raw, geom, attrs, load_id)
SELECT 'rigenerazione', s.cod_istat, s.id_ambito, s.denominazione, s.destinazione,
       ST_Multi(ST_MakeValid(s.geom)),
       to_jsonb(s) - 'geom' - 'stage_id',
       :load_id
FROM   planning_stage_rigenerazione s
WHERE  s.geom IS NOT NULL;
```

`ST_MakeValid` is not optional — municipal PGT polygons arrive with self-intersections
and slivers often enough that a strict load will fail partway through.

## 2. Cadastral parcels (catasto)

- **Bulk GML:** [Download massivo cartografia catastale](https://www.agenziaentrate.gov.it/portale/download-massivo-cartografia-catastale).
  National download is a ZIP organised region → province → one file per municipality;
  a regional download is a ZIP grouped by province. Updated **every six months**.
- **WFS:** `https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php`
  ([docs](https://www.agenziaentrate.gov.it/portale/cartografia-catastale-wfs))
- **WMS (raster):** `https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php`
  — WMS 1.3.0, `GetMap` capped at 2048×2048, `GetFeatureInfo` on the `Particelle` and
  `Mappe` layers. ([service manual](https://www.agenziaentrate.gov.it/portale/schede/fabbricatiterreni/consultazione-cartografia-catastale/servizio-consultazione-cartografia))
- **Licence:** CC-BY 4.0, commercial reuse allowed. Attribution is obligatory — store the
  required string in `meta.dataset_load.attribution` and render it in the map's
  attribution control.

**Two constraints that shape the product:**

1. **Parcels and sheets only — no buildings.** The bulk download does not include
   *fabbricati*. A "building footprint" layer has to come from elsewhere (regional DBT,
   or OSM). Don't promise building-level geometry off the catasto feed.
2. **Ownership data is not open.** Parcel *geometry* is CC-BY; owner identities come from
   *visure*, a separate paid/authenticated service with its own terms. A dashboard that
   joins owner names onto parcels is a different legal product. Keep that boundary
   explicit if investors will ask "who owns this?"

Load, per municipality, in parallel:

```bash
# Catasto GML is delivered in EPSG:6706 (RDN2008 geographic) and sometimes
# without a declared CRS at all — assign it, then reproject.
find /data/catasto/015 -name '*.gml' | parallel -j8 \
  ogr2ogr -f PostgreSQL "PG:host=$PGHOST dbname=edificai" \
    -append -nln cadastre.parcel_stage -nlt MULTIPOLYGON \
    -a_srs EPSG:6706 -t_srs EPSG:32632 -lco GEOMETRY_NAME=geom {}
```

Insert into the right partition by province, and swap partitions on each six-month
refresh rather than updating in place — it keeps the reload off the live table.

## 3. Energy certificates (APE / CENED)

- **Current database (CENED+2, DGR 3868/2015):**
  [dati.lombardia.it — Database CENED+2](https://dati.lombardia.it/Energia/Database-CENED-2-Certificazione-ENergetica-degli-E/bbky-sde5)
  — ~2.22M rows × 198 columns, updated weekly, published by Regione Lombardia via ARIA.
- **Legacy set (DDUO 5796/2009):**
  [CENED](https://www.dati.lombardia.it/Energia/CENED-Certificazione-ENergetica-degli-EDifici/rsg3-xhvk)
  — ~1.48M rows × 40 columns, monthly, CC0 1.0.
- **Residential-only view** (destinazione E.1(1)):
  [filtered view](https://dati.lombardia.it/Energia/CENED-Certificazione-ENergetica-degli-EDifici-filt/ajt8-fc6p)
- **Field dictionary:** the `Template_Descrizione_Campi_APE_Cened_ITA_ENG.pdf` attached
  to the CENED+2 page. With 198 columns you will need it.
- Both portals are Socrata; the `bbky-sde5` style identifier implies an API, but the
  pages themselves instruct you to pick CSV for the full dataset.

**The post's "1.9M residential certificates" is a filtered subset, not the raw file.**
CENED+2 is ~2.2M across all use classes; filtering to residential (`E.1*`) is what lands
near 1.9M. Reproduce that filter explicitly or your counts won't match.

**Certificates carry no geometry.** The only reliable spatial key is the municipality,
so energy metrics are municipality-level aggregates — that is exactly why
`energy.ape_by_comune` exists. Showing an APE-derived figure on a parcel popup implies
a precision the data does not have; label it as a municipal average.

```bash
# 2.2M x 198 columns: stream it, don't load it in pandas.
psql -c "\copy energy.ape_raw FROM '/data/cened2.csv' WITH (FORMAT csv, HEADER true)"
# then project the ~8 columns you actually query into energy.ape, rest into attrs
```

## 4. Administrative boundaries

ISTAT publishes *Confini delle unità amministrative a fini statistici* (generalised and
non-generalised, EPSG:32632, annual). **Unverified from this session** — confirm the
current year's download URL on istat.it before scripting against it.

Municipality counts drift: Lombardy mergers move the total year to year, so the "1,501
municipalities" figure is a vintage, not a constant. Pin the ISTAT release year in
`meta.dataset_load.source_updated` and key everything on `cod_istat`, which is stable
even when names and boundaries change.

## Refresh cadence

| Source | Publisher cadence | Suggested job |
|---|---|---|
| Catasto GML | 6 months | Quarterly check, partition swap on new release |
| CENED+2 | Weekly | Weekly incremental, then `REFRESH MATERIALIZED VIEW CONCURRENTLY energy.ape_by_comune` |
| PGT / rigenerazione / art. 40-bis | Irregular | Monthly poll of the metadata record's update date |
| ISTAT boundaries | Annual | Annual |

`REFRESH MATERIALIZED VIEW CONCURRENTLY` needs the unique index that the schema already
creates on `energy.ape_by_comune` and the generalised perimeter view — without it the
refresh takes an exclusive lock and the dashboard stalls.

## Licence summary

| Dataset | Licence | Obligation |
|---|---|---|
| Catasto (parcels, addresses) | CC-BY 4.0 | Attribution; commercial reuse permitted |
| CENED (legacy) | CC0 1.0 | None |
| CENED+2 | Check the portal's current terms | — |
| Geoportale Lombardia | Per-dataset, in the metadata record | Read each record |

Record the licence and attribution per load in `meta.dataset_load`. On a commercial
dashboard the attribution obligation is the one that gets missed.
