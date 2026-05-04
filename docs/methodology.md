# Phase 3 — Methodology Design
# Oyo Rural Suitability Engine

---

## 1. Overall Workflow

```
Raw spatial data
      │
      ▼
1. Preprocessing          — reproject, clip, resample, align to 30m grid
      │
      ▼
2. Criteria derivation    — produce one raster per criterion
      │
      ▼
3. Fuzzy standardisation  — convert each raster to [0, 1] suitability scale
      │
      ▼
4. AHP weighting          — derive weights via eigenvector method, check CR < 0.10
      │
      ▼
5. WLC + constraint mask  — S = Σ(wᵢ × cᵢ), hard-exclude constrained areas
      │
      ▼
6. Post-processing        — classify, uncertainty analysis, site ranking, reporting
```

---

## 2. Preprocessing

### 2.1 CRS Standardisation
All input data is reprojected from WGS84 (EPSG:4326) to UTM Zone 31N (EPSG:32631).
Reprojection uses bilinear resampling for continuous rasters; nearest-neighbour for categorical rasters (land cover).

### 2.2 Reference Grid
A single reference raster is created from the clipped DEM:
- Extent: study area + 5 km buffer
- Pixel size: 30 × 30 m
- All subsequent rasters are aligned to this grid

### 2.3 Data-Specific Steps

| Dataset | Steps |
|---|---|
| LGA boundaries | Dissolve 19 LGAs → reproject → study area polygon |
| DEM (SRTM) | Mosaic tiles → reproject → clip → derive slope |
| Land cover (10m) | Reproject → resample to 30m (mode) → clip → reclassify |
| NDVI (10m) | Reproject → resample to 30m (bilinear) → clip |
| Roads (vector) | Reproject → burn to proximity raster |
| Health facilities (vector) | Reproject → burn to proximity raster |
| Population (100m) | Reproject → resample to 30m → convert to density (p/km²) |
| Water bodies (vector) | Reproject → burn to proximity raster |
| Settlements (vector) | Reproject → extract centroids → burn to proximity raster |

---

## 3. Criteria Derivation

### 3.1 Proximity Rasters
Euclidean distance transform (scipy.ndimage.distance_transform_edt) on burned feature rasters.
Applied to: roads, health facilities, water bodies, settlements.

### 3.2 Slope
WhiteboxTools `slope` function (degrees), with NumPy gradient fallback:
`slope = arctan(√(dz/dx² + dz/dy²)) × (180/π)`

### 3.3 Land Cover Reclassification (ESA WorldCover)

| Code | Class | Healthcare score | Agriculture score |
|---|---|---|---|
| 10 | Cropland | 0.7 | 0.9 |
| 20 | Grassland/Savanna | 0.8 | 0.8 |
| 30 | Shrubland | 0.6 | 0.7 |
| 40 | Woodland/Forest | 0.3 | 0.3 |
| 50 | Built-up | 0.4 | 0.1 |
| 60 | Bare/Sparse | 0.5 | 0.0 |
| 70 | Water bodies | 0.0 | 0.0 |
| 80 | Permanent wetland | 0.0 | 0.0 |
| 90 | Herbaceous wetland | 0.2 | 0.4 |

---

## 4. Fuzzy Standardisation

### 4.1 Function Types

**Linear increase** (benefit — more is better):
```
μ(x) = 0                    if x ≤ low
μ(x) = (x−low)/(high−low)  if low < x < high
μ(x) = 1                    if x ≥ high
```

**Linear decrease** (cost — less is better):
```
μ(x) = 1                    if x ≤ low
μ(x) = (high−x)/(high−low) if low < x < high
μ(x) = 0                    if x ≥ high
```

**Trapezoidal** (optimal range):
```
μ(x) = 0              if x ≤ a
μ(x) = (x−a)/(b−a)   if a < x ≤ b
μ(x) = 1              if b < x ≤ c
μ(x) = (d−x)/(d−c)   if c < x ≤ d
μ(x) = 0              if x > d
```

### 4.2 Healthcare Fuzzy Parameters

| Criterion | Type | Parameters | Justification |
|---|---|---|---|
| Distance to health facility | Linear increase | low=0, high=10,000 m | WHO standard: facility within 5 km. Beyond 10 km = fully underserved |
| Population density | Linear increase | low=0, high=500 p/km² | Rural Oyo typical range 50–400 p/km². 500+ = high demand |
| Distance to roads | Linear decrease | low=0, high=3,000 m | Beyond 3 km from road, physical accessibility effectively zero |
| Distance to settlements | Linear decrease | low=0, high=5,000 m | Facility should serve settlement within 5 km walking radius |
| Slope | Linear decrease | low=0°, high=15° | Slopes > 15° require significant earthworks for construction |
| Land cover | Linear increase | low=0, high=1 | Pass-through of pre-classified score |

### 4.3 Agriculture Fuzzy Parameters

| Criterion | Type | Parameters | Justification |
|---|---|---|---|
| NDVI | Trapezoidal | a=0.1, b=0.3, c=0.7, d=0.9 | Below 0.1 = bare; 0.3–0.7 = optimal cropland/savanna; above 0.9 = dense forest |
| Land cover | Linear increase | low=0, high=1 | Pass-through of reclassified score |
| Slope | Linear decrease | low=0°, high=12° | FAO: slopes > 8° limit mechanised farming; > 12° limits manual cultivation |
| Distance to water | Trapezoidal | a=0, b=200, c=2,000, d=5,000 m | < 200 m = flood risk; 200–2,000 m = optimal irrigation zone |
| Distance to roads | Linear decrease | low=0, high=5,000 m | 5 km maximum for smallholder produce transport to market |
| Distance to settlements | Trapezoidal | a=0, b=500, c=3,000, d=8,000 m | Too close = land competition; 500–3,000 m = optimal labour access |

---

## 5. AHP Weighting

### 5.1 Method
AHP (Saaty, 1980) derives criteria weights from a pairwise comparison matrix.
The eigenvector of the normalised matrix gives the priority vector (weights).

### 5.2 Consistency Check
```
CI = (λmax − n) / (n − 1)
CR = CI / RI
```
CR must be < 0.10 to accept the matrix. RI values: n=6 → RI=1.24, n=7 → RI=1.32.

### 5.3 Healthcare Weights (AHP-derived)

Rationale: facility gap > population demand > road access > settlement proximity > terrain > land cover

| Criterion | Weight | Rationale |
|---|---|---|
| Distance to health facility | ~0.30 | Primary indicator of healthcare gap |
| Population density | ~0.25 | Demand signal |
| Distance to roads | ~0.19 | Physical accessibility |
| Distance to settlements | ~0.12 | Service proximity |
| Slope | ~0.09 | Construction feasibility |
| Land cover | ~0.05 | Secondary engineering constraint |

### 5.4 Agriculture Weights (AHP-derived)

Rationale: vegetation condition > land class > terrain + water (equal) > market access > labour access

| Criterion | Weight | Rationale |
|---|---|---|
| NDVI | ~0.28 | Direct indicator of agricultural potential |
| Land cover | ~0.20 | Structural land classification |
| Slope | ~0.16 | Hard biophysical constraint |
| Distance to water | ~0.16 | Irrigation potential |
| Distance to roads | ~0.10 | Market/input access |
| Distance to settlements | ~0.10 | Labour and service access |

---

## 6. Weighted Linear Combination (WLC)

```
S(x,y) = Σᵢ [wᵢ × μᵢ(x,y)] × C(x,y)
```
- S(x,y) = suitability score at pixel (x,y), range [0, 1]
- wᵢ = AHP-derived weight for criterion i (Σwᵢ = 1)
- μᵢ(x,y) = fuzzy standardised value of criterion i at pixel (x,y)
- C(x,y) = constraint mask (1 = valid, 0 = excluded → NoData)

---

## 7. Constraint Masking

| Constraint | Healthcare | Agriculture | Source |
|---|---|---|---|
| Water bodies (permanent) | Excluded | Excluded | ESA class 70 |
| Steep slopes > 20° | Excluded | — | DEM-derived |
| Steep slopes > 15° | — | Excluded | DEM-derived |
| Protected areas | Excluded | Excluded | WDPA |
| Flood zones (1-in-100yr) | Excluded | Not excluded | FATHOM |
| Urban built-up | Not excluded | Excluded | ESA class 50 |

---

## 8. Suitability Classification

| Class | Label | Score range |
|---|---|---|
| 5 | Very High | 0.80 – 1.00 |
| 4 | High | 0.60 – 0.80 |
| 3 | Moderate | 0.40 – 0.60 |
| 2 | Low | 0.20 – 0.40 |
| 1 | Very Low | 0.00 – 0.20 |

---

## 9. Uncertainty Analysis

Monte Carlo: 1,000 iterations × ±10% weight perturbation → renormalise → recompute WLC.

Output rasters:
- Mean suitability — more robust than single-run result
- Standard deviation — per-pixel sensitivity to weight assumptions
- Coefficient of variation (CV) = std/mean — normalised uncertainty

---

## 10. Candidate Site Ranking

1. Threshold at min score (0.65 healthcare, 0.60 agriculture)
2. Vectorise contiguous patches
3. Filter by min area (0.5 ha healthcare, 5.0 ha agriculture)
4. Attach attributes: mean/max suitability, area, road distance, uncertainty CV, population within 5 km
5. Composite rank score (normalised average of attributes)
6. Export top 20 per model to GeoPackage

---

## 11. References

- Saaty, T.L. (1980). The Analytic Hierarchy Process. McGraw-Hill, New York.
- Malczewski, J. (1999). GIS and Multicriteria Decision Analysis. John Wiley & Sons.
- Zadeh, L.A. (1965). Fuzzy sets. Information and Control, 8(3), 338–353.
- Eastman, J.R. (1999). Multi-criteria evaluation and GIS. Geographical Information Systems, 1(1), 493–502.
- WHO (2010). Classifying health workers. World Health Organization, Geneva.
- FAO (1976). A Framework for Land Evaluation. FAO Soils Bulletin 32.
