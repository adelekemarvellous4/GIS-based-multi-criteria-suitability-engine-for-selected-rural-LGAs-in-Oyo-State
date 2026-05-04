# Data Sources

## Required Datasets

| Dataset | Source | Resolution | Format | Download URL | Target Path |
|---|---|---|---|---|---|
| LGA Boundaries (Nigeria ADM2) | geoBoundaries | Vector | GeoJSON/SHP | https://www.geoboundaries.org/api/current/gbOpen/NGA/ADM2/ | `data/raw/boundaries/` |
| Roads | OpenStreetMap via OSMnx | Vector | Auto-downloaded | Script: `data_acquisition.py` | `data/raw/roads/` |
| Health Facilities | GRID3 Nigeria | Vector | CSV/SHP | https://grid3.org/resources/health-facilities | `data/raw/health_facilities/` |
| Health Facilities (OSM fallback) | OpenStreetMap via OSMnx | Vector | Auto-downloaded | Script: `data_acquisition.py` | `data/raw/health_facilities/` |
| Population | WorldPop Nigeria 100m | 100m raster | GeoTIFF | https://hub.worldpop.org/geodata/listing?id=29 | `data/raw/population/` |
| DEM (Elevation) | SRTM 1 Arc-Second | 30m raster | GeoTIFF | https://earthexplorer.usgs.gov/ | `data/raw/dem/` |
| Land Cover | ESA WorldCover 2021 | 10m raster | GeoTIFF | https://worldcover2021.esa.int/downloader | `data/raw/land_cover/` |
| NDVI | Sentinel-2 / Landsat via GEE | 10–30m raster | GeoTIFF | https://code.earthengine.google.com/ | `data/raw/ndvi/` |
| Water Bodies / Rivers | OpenStreetMap via OSMnx | Vector | Auto-downloaded | Script: `data_acquisition.py` | `data/raw/water/` |
| Settlements | OpenStreetMap / GRID3 | Vector | GeoJSON | https://data.humdata.org/ | `data/raw/settlements/` |

---

## Manual Download Instructions

### DEM — SRTM 30m
1. Go to https://earthexplorer.usgs.gov/
2. Draw a search polygon covering Oyo State (bbox: 2.80W, 6.80S, 4.80E, 9.30N)
3. Under *Data Sets*, select: `Digital Elevation > SRTM > SRTM 1 Arc-Second Global`
4. Download all tiles covering the study area
5. Save to `data/raw/dem/`

### Population — WorldPop
1. Go to https://hub.worldpop.org/geodata/listing?id=29
2. Download the Nigeria 100m population grid (latest year available)
3. Save to `data/raw/population/`

### Land Cover — ESA WorldCover 2021
1. Go to https://worldcover2021.esa.int/downloader
2. Select tiles covering Nigeria
3. Download 10m GeoTIFF tiles
4. Save to `data/raw/land_cover/`

### NDVI — Google Earth Engine
Use the GEE script below to export a median NDVI composite for the study area:

```javascript
// Google Earth Engine Script — Sentinel-2 NDVI Composite
var studyArea = ee.Geometry.Rectangle([2.80, 6.80, 4.80, 9.30]);
var s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(studyArea)
  .filterDate('2022-01-01', '2023-12-31')
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
  .map(function(img) {
    var ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI');
    return ndvi;
  });

var medianNDVI = s2.median().clip(studyArea);

Export.image.toDrive({
  image: medianNDVI,
  description: 'oyo_ndvi_sentinel2_median',
  scale: 10,
  region: studyArea,
  fileFormat: 'GeoTIFF',
  maxPixels: 1e10
});
```

Save exported file to `data/raw/ndvi/`.

### Health Facilities — GRID3
1. Go to https://grid3.org/resources/health-facilities
2. Download Nigeria Health Facilities dataset
3. Save to `data/raw/health_facilities/`

---

## Notes on CRS
- All raw data should be downloaded in **WGS84 (EPSG:4326)**
- Preprocessing scripts will reproject everything to **UTM Zone 31N (EPSG:32631)**
- Do not manually reproject raw data — the pipeline handles this

## Notes on Resolution
- Target analysis resolution: **30 metres**
- Higher-resolution inputs (10m land cover, 10m NDVI) will be resampled down
- Lower-resolution inputs (100m population) will be resampled up with bilinear interpolation
