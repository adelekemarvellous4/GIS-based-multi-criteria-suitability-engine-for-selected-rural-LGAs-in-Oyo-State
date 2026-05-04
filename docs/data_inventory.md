# Phase 2 — Data Inventory
# Oyo Rural Suitability Engine

## Confirmed Study Area

**19 Rural LGAs across 3 Senatorial Districts of Oyo State**

| Senatorial District | LGAs | Count |
|---|---|---|
| **Oyo Central** | Afijio, Atiba, Oyo East, Oyo West | 4 |
| **Oyo North** | Atisbo, Irepo, Iseyin, Itesiwaju, Iwajowa, Kajola, Olorunsogo, Oriire, Saki East, Saki West, Surulere | 11 |
| **Oyo South** | Ibarapa Central, Ibarapa East, Ibarapa North, Ido | 4 |
| **Total** | | **19** |

**Bounding Box (WGS84):** West 2.90° | East 4.40° | South 7.00° | North 9.20°
**Projected CRS:** UTM Zone 31N (EPSG:32631)
**Analysis resolution:** 30m

---

## Complete Dataset Inventory

### Legend
- 🟢 Auto — downloaded automatically by `src/data_acquisition.py`
- 🟡 Manual — requires manual download from web portal
- 🔵 GEE — requires Google Earth Engine script export
- ⚪ Optional — not required for core model

---

### Boundary & Administrative

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 1 | LGA administrative boundaries (ADM2) | geoBoundaries / GADM | Vector | GeoJSON / SHP | 🟢 Auto | `data/raw/boundaries/` | Both |

**Notes:**
- geoBoundaries API: `https://www.geoboundaries.org/api/current/gbOpen/NGA/ADM2/`
- Filter to Oyo State after download
- Must match official LGA names exactly for joining attributes

---

### Transport & Accessibility

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 2 | Road network (all road types) | OpenStreetMap via OSMnx | Vector | GeoPackage | 🟢 Auto | `data/raw/roads/` | Both |
| 3 | Settlement points / centroids | OpenStreetMap via OSMnx | Vector | GeoPackage | 🟢 Auto | `data/raw/settlements/` | Both |

**Notes:**
- OSMnx `network_type="all"` captures motorways, trunk roads, primary, secondary, tertiary, unclassified, and tracks — all relevant for rural accessibility
- Settlement polygons will be converted to centroids in preprocessing

---

### Healthcare

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 4 | Health facility locations | GRID3 Nigeria | Vector | CSV / SHP | 🟡 Manual | `data/raw/health_facilities/` | Healthcare |
| 5 | Health facility locations (fallback) | OpenStreetMap via OSMnx | Vector | GeoPackage | 🟢 Auto | `data/raw/health_facilities/` | Healthcare |

**GRID3 Download:**
- URL: `https://grid3.org/resources/health-facilities`
- Select Nigeria → Health Facilities dataset
- Preferred over OSM — GRID3 is more complete for Nigerian rural facilities
- Attribute fields to keep: `facility_name`, `facility_type`, `latitude`, `longitude`, `admin2` (LGA)

---

### Population

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 6 | Population count grid | WorldPop Nigeria (unconstrained, 100m) | 100m | GeoTIFF | 🟡 Manual | `data/raw/population/` | Healthcare |

**Download:**
- URL: `https://hub.worldpop.org/geodata/listing?id=29`
- Dataset: "Nigeria — Population Counts — 100m resolution"
- Download the most recent year available (2020 preferred)
- File will cover all of Nigeria — clipping to study area done in preprocessing

---

### Elevation & Terrain

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 7 | Digital Elevation Model (SRTM) | USGS EarthExplorer | 30m (~1 arc-second) | GeoTIFF | 🟡 Manual | `data/raw/dem/` | Both |

**Download steps:**
1. Go to `https://earthexplorer.usgs.gov/` — requires free account
2. Under "Search Criteria" → draw polygon or enter coordinates:
   - UL: 9.20°N, 2.90°E | LR: 7.00°N, 4.40°E
3. Under "Data Sets": Digital Elevation → SRTM → SRTM 1 Arc-Second Global
4. Download all tiles covering the bbox (expect 2–4 tiles)
5. Save to `data/raw/dem/` — preprocessing will mosaic and clip

**Derived layers** (generated in `src/preprocessing.py`):
- `slope_degrees.tif` — slope in degrees (WhiteboxTools / NumPy fallback)
- `aspect_degrees.tif` — aspect (optional, for later analysis)

---

### Land Cover

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 8 | Land cover classification | ESA WorldCover 2021 | 10m | GeoTIFF | 🟡 Manual | `data/raw/land_cover/` | Both |

**Download:**
- URL: `https://worldcover2021.esa.int/downloader`
- Select tiles covering bbox (1–2 tiles expected for study area)
- 11-class scheme: Tree cover, Shrubland, Grassland, Cropland, Built-up, Bare/sparse, Snow/ice, Permanent water, Herbaceous wetland, Mangroves, Moss/lichen
- Reclassification to suitability scores defined in `config/agriculture_config.yml` under `land_cover_reclass`

**Alternative (if WorldCover unavailable):**
- GlobCover 2009: `http://due.esrin.esa.int/page_globcover.php`

---

### Vegetation (NDVI)

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 9 | NDVI composite (median, dry/wet season) | Sentinel-2 via Google Earth Engine | 10m | GeoTIFF | 🔵 GEE | `data/raw/ndvi/` | Agriculture |

**GEE Export Script** (already in `docs/data_sources.md`):
- Median composite, 2022–2023, <20% cloud cover
- Export at 10m resolution
- Consider exporting both a **wet season** (May–Oct) and **dry season** (Nov–Apr) composite for sensitivity analysis

**GEE script filename:** `gee_ndvi_sentinel2_export.js`

---

### Water Bodies & Hydrology

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 10 | Water bodies and rivers (OSM) | OpenStreetMap via OSMnx | Vector | GeoPackage | 🟢 Auto | `data/raw/water/` | Agriculture |
| 11 | Stream network (detailed) | HydroSHEDS / HydroRIVERS | ~90m / Vector | SHP | 🟡 Manual | `data/raw/water/` | Agriculture |

**HydroRIVERS Download:**
- URL: `https://www.hydrosheds.org/products/hydrorivers`
- Download Africa layer (Level 4–6 streams suitable for proximity analysis)
- Clip to study area in preprocessing

---

### Environmental Constraints

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 12 | Flood hazard zones | FATHOM Global Flood Model | ~90m | GeoTIFF | 🟡 Manual | `data/raw/constraints/flood/` | Both |
| 13 | Protected areas | WDPA (World Database of Protected Areas) | Vector | SHP / GeoJSON | 🟡 Manual | `data/raw/constraints/protected/` | Both |

**Flood data:**
- FATHOM: `https://www.fathom.global/` — commercial but free academic access
- Alternative: UNOSAT Flood Monitoring or JRC Global Surface Water (`https://global-surface-water.appspot.com/`)

**Protected areas:**
- WDPA: `https://www.protectedplanet.net/en/thematic-areas/wdpa`
- Download Nigeria shapefile → filter to Oyo State in preprocessing

---

### Optional / Enhancement Datasets

| # | Dataset | Source | Resolution | Format | Acquisition | Target Path | Models |
|---|---|---|---|---|---|---|---|
| 14 | Soil suitability | ISRIC SoilGrids | 250m | GeoTIFF | ⚪ Optional | `data/external/soil/` | Agriculture |
| 15 | Nighttime lights | VIIRS / NASA Black Marble | 500m | GeoTIFF | ⚪ Optional | `data/external/ntl/` | Healthcare |
| 16 | Market locations | OpenStreetMap / HDX | Vector | CSV | ⚪ Optional | `data/external/markets/` | Agriculture |

**SoilGrids:**
- URL: `https://www.isric.org/explore/soilgrids`
- Variables to consider: `phh2o` (soil pH), `soc` (organic carbon), `clay` (texture)
- 250m resolution — will be resampled to 30m (lower confidence at coarser source)

---

## Download Priority Order

Start with the datasets that block the most downstream work:

| Priority | Dataset | Reason |
|---|---|---|
| 1 | LGA boundaries | Needed for all clipping and masking |
| 2 | SRTM DEM | Needed for slope (both models) |
| 3 | ESA WorldCover | Needed for land cover criterion (both models) |
| 4 | GRID3 health facilities | Core criterion for healthcare model |
| 5 | WorldPop population | Core criterion for healthcare model |
| 6 | Roads (OSM) | Auto-downloaded — run script |
| 7 | Water bodies (OSM) | Auto-downloaded — run script |
| 8 | NDVI (GEE) | Requires GEE account — start this early |
| 9 | HydroRIVERS | Supplementary water network |
| 10 | Flood zones | Constraint mask (can add later) |
| 11 | Protected areas | Constraint mask (can add later) |

---

## Data Checklist

Run this checklist before starting Phase 5 (Preprocessing):

- [ ] `data/raw/boundaries/oyo_lga_boundaries.gpkg` — 19 LGAs present
- [ ] `data/raw/dem/` — SRTM tiles downloaded, cover full bbox
- [ ] `data/raw/land_cover/` — ESA WorldCover tile(s) downloaded
- [ ] `data/raw/health_facilities/` — GRID3 CSV or SHP downloaded
- [ ] `data/raw/population/` — WorldPop Nigeria GeoTIFF downloaded
- [ ] `data/raw/roads/roads_osm.gpkg` — generated by script
- [ ] `data/raw/water/water_bodies_osm.gpkg` — generated by script
- [ ] `data/raw/water/hydrorivers_africa.shp` — downloaded
- [ ] `data/raw/ndvi/oyo_ndvi_sentinel2_median.tif` — exported from GEE
- [ ] `data/raw/constraints/flood/` — flood raster downloaded (or noted as deferred)
- [ ] `data/raw/constraints/protected/` — WDPA shapefile downloaded
