# Oyo Rural Suitability Engine

> A Reproducible GIS-Based Multi-Criteria Suitability Engine for Healthcare and Agricultural Planning in Rural LGAs of Oyo State, Nigeria

---

## Overview

This project develops an **automated, reproducible GIS-based suitability engine** for identifying and ranking optimal locations for:

- 🏥 **Healthcare facilities** — prioritising underserved rural zones
- 🌾 **Agricultural development** — identifying high-potential farming zones

The engine is designed to be reusable: changing the configuration file and input datasets allows the same workflow to be reproduced for any study area.

---

## Project Structure

```
oyo-rural-suitability-engine/
│
├── README.md
├── environment.yml          ← Conda environment spec
├── requirements.txt         ← Pip alternative
│
├── config/
│   ├── study_area_config.yml     ← LGAs, CRS, bbox, resolution
│   ├── healthcare_config.yml     ← Criteria, weights, thresholds
│   └── agriculture_config.yml   ← Criteria, weights, thresholds
│
├── data/
│   ├── raw/            ← Downloaded source datasets (do not modify)
│   ├── interim/        ← Preprocessed/reprojected data
│   ├── processed/      ← Standardised criteria rasters
│   └── external/       ← Third-party reference data
│
├── notebooks/
│   ├── 01_project_overview.ipynb
│   ├── 02_data_preprocessing.ipynb
│   ├── 03_healthcare_suitability.ipynb
│   ├── 04_agriculture_suitability.ipynb
│   ├── 05_uncertainty_analysis.ipynb
│   └── 06_candidate_site_ranking.ipynb
│
├── src/
│   ├── utils.py                  ← Shared utilities, config loading, logging
│   ├── data_acquisition.py       ← OSM, GADM, and data source helpers
│   ├── preprocessing.py          ← Reproject, clip, resample, slope, proximity
│   ├── fuzzy_standardisation.py  ← Fuzzy membership functions
│   ├── ahp.py                    ← AHP weight derivation + consistency check
│   ├── suitability_model.py      ← WLC engine + constraint masking
│   ├── uncertainty.py            ← Monte Carlo uncertainty analysis
│   ├── site_ranking.py           ← Candidate site extraction and ranking
│   ├── criteria_derivation.py    ← (Phase 5) Derive raw criteria from inputs
│   └── reporting.py              ← (Phase 10) Automated PDF report generation
│
├── outputs/
│   ├── rasters/    ← Suitability, uncertainty, and constraint rasters
│   ├── vectors/    ← Candidate site polygons (GeoPackage)
│   ├── maps/       ← Exported map figures (PNG/PDF)
│   ├── reports/    ← Automated PDF reports
│   └── dashboards/ ← Dashboard static exports
│
├── dashboard/
│   ├── app.py      ← Streamlit WebGIS dashboard
│   └── assets/
│
└── docs/
    ├── methodology.md
    ├── data_sources.md
    └── project_notes.md
```

---

## Models

### 1. Healthcare Suitability Model

**Research question:** Where are the most suitable locations for new rural healthcare facilities in Oyo State?

| Criterion | Logic | Weight |
|---|---|---|
| Distance to existing health facilities | Farther = higher need | 0.30 |
| Population density | Higher = higher demand | 0.25 |
| Distance to roads | Closer = better access | 0.20 |
| Distance to settlements | Closer = better | 0.10 |
| Slope | Gentler = better | 0.10 |
| Land cover | Open/built land preferred | 0.05 |

### 2. Agriculture Suitability Model

**Research question:** Where are the most suitable zones for agricultural development in rural Oyo State?

| Criterion | Logic | Weight |
|---|---|---|
| NDVI | Moderate–high vegetation | 0.25 |
| Land cover | Cropland/grassland preferred | 0.20 |
| Slope | Gentler = more suitable | 0.20 |
| Distance to water | Moderately close | 0.15 |
| Distance to roads | Closer = better market access | 0.10 |
| Settlement proximity | Moderate = labour access | 0.10 |

---

## Quick Start

### 1. Set up the environment

```bash
# With conda/mamba (recommended)
conda env create -f environment.yml
conda activate oyo-suitability

# Or with pip
pip install -r requirements.txt
```

### 2. Download required data

See [`docs/data_sources.md`](docs/data_sources.md) for data download instructions, or run:

```python
from src.data_acquisition import print_data_sources
print_data_sources()
```

### 3. Run the notebooks in order

```
notebooks/01_project_overview.ipynb
notebooks/02_data_preprocessing.ipynb
notebooks/03_healthcare_suitability.ipynb
notebooks/04_agriculture_suitability.ipynb
notebooks/05_uncertainty_analysis.ipynb
notebooks/06_candidate_site_ranking.ipynb
```

### 4. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

---

## Technical Stack

| Category | Tools |
|---|---|
| GIS / Spatial | Rasterio, GeoPandas, GDAL, OSMnx, WhiteboxTools, Shapely |
| Analysis | NumPy, SciPy, PyMCDA |
| Visualisation | Matplotlib, Contextily, Folium |
| Reporting | ReportLab / FPDF2 |
| Dashboard | Streamlit |
| Config | YAML |
| Reproducibility | Jupyter, GitHub, conda environment |

---

## Study Area

**19 confirmed rural LGAs** across all three senatorial districts of Oyo State, Nigeria.

| District | LGAs |
|---|---|
| Oyo Central (4) | Afijio, Atiba, Oyo East, Oyo West |
| Oyo North (11) | Atisbo, Irepo, Iseyin, Itesiwaju, Iwajowa, Kajola, Olorunsogo, Oriire, Saki East, Saki West, Surulere |
| Oyo South (4) | Ibarapa Central, Ibarapa East, Ibarapa North, Ido |

Bounding box (WGS84): 2.90°–4.40°E, 7.00°–9.20°N. CRS: UTM Zone 31N (EPSG:32631). Resolution: 30m.

See [`docs/data_inventory.md`](docs/data_inventory.md) for the full dataset checklist and download instructions.

---

## Author

*[Your name and affiliation]*

## License

MIT
