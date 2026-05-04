"""
run_site_ranking.py
-------------------
Phase 9 — Candidate site extraction and ranking.

Extracts high-suitability zones, filters by minimum area,
attaches ranking attributes, and exports top-N sites per model.

Usage:
    python src/run_site_ranking.py --model healthcare
    python src/run_site_ranking.py --model agriculture
    python src/run_site_ranking.py --model both
"""

import sys
import argparse
import numpy as np
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

from utils import setup_logger, load_config

logger = setup_logger("site_ranking")

INTERIM = ROOT_DIR / "data/interim"
OUT_R   = ROOT_DIR / "outputs/rasters"
OUT_V   = ROOT_DIR / "outputs/vectors"
OUT_M   = ROOT_DIR / "outputs/maps"
OUT_V.mkdir(exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
def run_ranking(model_name: str):
    print(f"\n{'='*60}")
    print(f"  CANDIDATE SITE RANKING — {model_name.upper()}")
    print(f"{'='*60}")

    cfg      = load_config(ROOT_DIR / f"config/{model_name}_config.yml")
    rank_cfg = cfg["site_ranking"]

    suit_path = OUT_R / f"{model_name}_suitability.tif"
    cv_path   = OUT_R / f"{model_name}_uncertainty_cv.tif"
    mask_path = OUT_R / f"{model_name}_constraint_mask.tif"
    out_gpkg  = OUT_V / f"{model_name}_candidate_sites.gpkg"

    if not suit_path.exists():
        print(f"  [FAIL] Suitability raster not found: {suit_path.name}")
        print(f"  Run: python src/run_suitability.py --model {model_name}")
        return False

    # ── Step 1: Extract candidate patches ────────────────────────────────
    min_score   = rank_cfg["min_suitability_score"]
    min_area_ha = rank_cfg["min_patch_area_ha"]
    top_n       = rank_cfg["top_n_sites"]

    print(f"\n[1] Extracting candidate sites...")
    print(f"  Min suitability score : {min_score}")
    print(f"  Min patch area        : {min_area_ha} ha")

    import rasterio
    from rasterio.features import shapes
    import geopandas as gpd
    from shapely.geometry import shape
    import pandas as pd

    with rasterio.open(suit_path) as src:
        arr       = src.read(1).astype("float32")
        transform = src.transform
        crs       = src.crs
        nodata    = src.nodata
        pixel_area_ha = abs(transform.a * transform.e) / 10_000

    # Binary mask of qualifying pixels
    valid = (arr >= min_score)
    if nodata is not None:
        valid &= (arr != nodata)
    valid &= ~np.isnan(arr)

    print(f"  Qualifying pixels     : {valid.sum():,}  "
          f"({valid.sum() * pixel_area_ha:,.0f} ha)")

    # Vectorise contiguous patches
    binary = valid.astype("uint8")
    patches = []
    for geom_dict, val in shapes(binary, mask=binary, transform=transform):
        if val == 1:
            poly = shape(geom_dict)
            area_ha = poly.area / 10_000
            if area_ha >= min_area_ha:
                patches.append({"geometry": poly, "area_ha": round(area_ha, 2)})

    print(f"  Patches extracted     : {len(patches):,}")
    if not patches:
        print(f"  [WARN] No patches found. Try lowering min_suitability_score "
              f"(currently {min_score}) or min_patch_area_ha (currently {min_area_ha}).")
        return False

    sites = gpd.GeoDataFrame(patches, crs=crs)
    print(f"  Total candidate area  : {sites['area_ha'].sum():,.0f} ha")

    # ── Step 2: Attach suitability stats per patch ───────────────────────
    print(f"\n[2] Computing per-patch suitability statistics...")
    from rasterio.mask import mask as rmask

    mean_scores, max_scores = [], []
    for idx, row in sites.iterrows():
        try:
            with rasterio.open(suit_path) as src:
                out_img, _ = rmask(src, [row.geometry.__geo_interface__],
                                   crop=True, nodata=np.nan)
            vals = out_img[~np.isnan(out_img)]
            vals = vals[vals > 0]
            mean_scores.append(round(float(np.mean(vals)), 4) if len(vals) else 0)
            max_scores.append(round(float(np.max(vals)), 4) if len(vals) else 0)
        except Exception:
            mean_scores.append(0)
            max_scores.append(0)

    sites["mean_suitability"] = mean_scores
    sites["max_suitability"]  = max_scores

    # ── Step 3: Attach uncertainty score ─────────────────────────────────
    print(f"\n[3] Attaching uncertainty scores...")
    if cv_path.exists():
        centroids = sites.geometry.centroid
        with rasterio.open(cv_path) as src:
            coords = [(pt.x, pt.y) for pt in centroids]
            cv_vals = [list(src.sample([(x, y)]))[0][0] for x, y in coords]
        sites["uncertainty_cv"] = [round(float(v), 4) for v in cv_vals]
        print(f"  Uncertainty CV attached from {cv_path.name}")
    else:
        sites["uncertainty_cv"] = 0.0
        print(f"  [SKIP] CV raster not found — uncertainty set to 0")

    # ── Step 4: Attach distance to nearest road ──────────────────────────
    print(f"\n[4] Attaching road accessibility...")
    roads_path = ROOT_DIR / "data/raw/roads/oyo_rural_highway.gpkg"
    if not roads_path.exists():
        roads_path = next(
            (p for p in (ROOT_DIR / "data/raw/roads").glob("*.gpkg")), None)

    if roads_path and roads_path.exists():
        roads = gpd.read_file(roads_path).to_crs(crs)
        roads_union = roads.geometry.unary_union
        sites["dist_to_road_m"] = sites.geometry.centroid.distance(roads_union).round(0)
        print(f"  Distance to road attached ({roads_path.name})")
    else:
        sites["dist_to_road_m"] = np.nan
        print(f"  [SKIP] Roads file not found")

    # ── Step 5: Attach population within 5km (healthcare only) ───────────
    if model_name == "healthcare":
        print(f"\n[5] Estimating population within 5km radius...")
        pop_path = INTERIM / "population_30m_aligned.tif"
        if pop_path.exists():
            pop_within = []
            radius_m = rank_cfg.get("population_radius_m", 5000)
            for _, row in sites.iterrows():
                try:
                    buf = row.geometry.centroid.buffer(radius_m)
                    with rasterio.open(pop_path) as src:
                        out_img, _ = rmask(src, [buf.__geo_interface__],
                                           crop=True, nodata=0)
                    total_pop = float(np.nansum(out_img[out_img > 0]))
                    pop_within.append(round(total_pop))
                except Exception:
                    pop_within.append(0)
            sites["pop_within_5km"] = pop_within
            print(f"  Population within {radius_m/1000:.0f}km attached")
        else:
            sites["pop_within_5km"] = 0
            print(f"  [SKIP] Population raster not found")
    else:
        print(f"\n[5] Skipping population radius (agriculture model)")

    # ── Step 6: Composite ranking ─────────────────────────────────────────
    print(f"\n[6] Computing composite rank score...")

    def normalise(series, invert=False):
        rng = series.max() - series.min()
        if rng == 0:
            return series * 0 + 0.5
        norm = (series - series.min()) / rng
        return 1 - norm if invert else norm

    score_components = []

    # Suitability score — higher is better
    sites["_n_suit"] = normalise(sites["mean_suitability"])
    score_components.append(("_n_suit", 0.40))

    # Area — larger is better
    sites["_n_area"] = normalise(sites["area_ha"])
    score_components.append(("_n_area", 0.20))

    # Uncertainty — lower CV is better
    if sites["uncertainty_cv"].sum() > 0:
        sites["_n_cert"] = normalise(sites["uncertainty_cv"], invert=True)
        score_components.append(("_n_cert", 0.20))

    # Road distance — closer is better
    if sites["dist_to_road_m"].notna().any():
        sites["_n_road"] = normalise(sites["dist_to_road_m"], invert=True)
        score_components.append(("_n_road", 0.10))

    # Population (healthcare) — higher is better
    if model_name == "healthcare" and "pop_within_5km" in sites.columns:
        sites["_n_pop"] = normalise(sites["pop_within_5km"])
        score_components.append(("_n_pop", 0.10))

    # Normalise component weights to sum to 1
    total_w = sum(w for _, w in score_components)
    sites["composite_score"] = sum(
        sites[col] * (w / total_w) for col, w in score_components
    ).round(4)

    # Drop normalisation helper columns
    sites = sites[[c for c in sites.columns if not c.startswith("_n_")]]

    # ── Step 7: Select top N and rank ─────────────────────────────────────
    print(f"\n[7] Selecting top {top_n} sites...")
    top_sites = (sites
                 .sort_values("composite_score", ascending=False)
                 .head(top_n)
                 .copy()
                 .reset_index(drop=True))
    top_sites["rank"] = range(1, len(top_sites) + 1)

    # Reorder columns
    col_order = ["rank", "composite_score", "mean_suitability", "max_suitability",
                 "area_ha", "dist_to_road_m", "uncertainty_cv"]
    if model_name == "healthcare":
        col_order.append("pop_within_5km")
    col_order.append("geometry")
    col_order = [c for c in col_order if c in top_sites.columns]
    top_sites = top_sites[col_order]

    # ── Step 8: Save ─────────────────────────────────────────────────────
    print(f"\n[8] Saving outputs...")
    top_sites.to_file(out_gpkg, driver="GPKG")
    print(f"  [OK  ] {out_gpkg.name}  ({len(top_sites)} sites)")

    # Also save all candidate sites (not just top N)
    all_gpkg = OUT_V / f"{model_name}_all_candidate_sites.gpkg"
    sites.sort_values("composite_score", ascending=False).to_file(
        all_gpkg, driver="GPKG")
    print(f"  [OK  ] {all_gpkg.name}  ({len(sites)} sites total)")

    # ── Step 9: Print results table ───────────────────────────────────────
    print(f"\n{'─'*70}")
    print(f"  TOP {len(top_sites)} {model_name.upper()} CANDIDATE SITES")
    print(f"{'─'*70}")

    display_cols = ["rank","composite_score","mean_suitability",
                    "area_ha","dist_to_road_m","uncertainty_cv"]
    if model_name == "healthcare":
        display_cols.append("pop_within_5km")
    display_cols = [c for c in display_cols if c in top_sites.columns]

    # Header
    widths = [5, 12, 14, 10, 14, 13, 13]
    headers = ["Rank","Composite","Mean suit.","Area(ha)","Dist road(m)","Uncert.CV","Pop 5km"]
    hdr = "  " + "".join(f"{h:<{w}}" for h, w in zip(headers, widths))
    print(hdr)
    print("  " + "─" * (sum(widths)))

    for _, row in top_sites.iterrows():
        vals = [
            f"{int(row['rank'])}",
            f"{row['composite_score']:.4f}",
            f"{row['mean_suitability']:.4f}",
            f"{row['area_ha']:.1f}",
            f"{row['dist_to_road_m']:.0f}" if not np.isnan(row.get('dist_to_road_m',np.nan)) else "N/A",
            f"{row['uncertainty_cv']:.4f}",
        ]
        if model_name == "healthcare" and "pop_within_5km" in row:
            vals.append(f"{int(row['pop_within_5km']):,}")
        line = "  " + "".join(f"{v:<{w}}" for v, w in zip(vals, widths))
        print(line)

    # ── Step 10: Summary map ─────────────────────────────────────────────
    print(f"\n[9] Generating candidate sites map...")
    _plot_sites(top_sites, suit_path, model_name, crs)

    print(f"\n  Site ranking complete — {model_name}.")
    print(f"  {len(top_sites)} top sites saved to: outputs/vectors/")
    return True


# ════════════════════════════════════════════════════════════════════════════
def _plot_sites(sites_gdf, suit_path, model_name, crs):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import matplotlib.patches as mpatches
        import rasterio
        from matplotlib.cm import ScalarMappable

        fig, ax = plt.subplots(1, 1, figsize=(12, 10))
        cmap_suit = "RdYlGn" if model_name == "healthcare" else "YlGn"
        site_color = "#c0392b" if model_name == "healthcare" else "#1a5276"

        # Background suitability raster
        with rasterio.open(suit_path) as src:
            arr = src.read(1).astype(float)
            nd  = src.nodata
            ext = [src.bounds.left, src.bounds.right,
                   src.bounds.bottom, src.bounds.top]
        arr_m = np.where((arr == nd) | (arr <= 0), np.nan, arr)
        im = ax.imshow(arr_m, cmap=cmap_suit, vmin=0, vmax=1,
                       extent=ext, origin="upper", alpha=0.80)
        plt.colorbar(im, ax=ax, fraction=0.025, pad=0.01,
                     label="Suitability score [0–1]")

        # Study area boundary
        sa_path = ROOT_DIR / "data/interim/study_area.gpkg"
        if sa_path.exists():
            import geopandas as gpd
            sa = gpd.read_file(sa_path).to_crs(crs)
            sa.boundary.plot(ax=ax, color="white", linewidth=0.6,
                             linestyle="--", alpha=0.8)

        # Site polygons coloured by rank
        sites_proj = sites_gdf.to_crs(crs)
        n = len(sites_proj)
        cmap_rank = plt.cm.get_cmap("autumn_r", n)

        for idx, (_, row) in enumerate(sites_proj.iterrows()):
            color = cmap_rank(idx / max(n-1, 1))
            ax.fill(*row.geometry.exterior.xy,
                    alpha=0.75, color=color, zorder=3)
            ax.plot(*row.geometry.exterior.xy,
                    color="white", linewidth=0.5, zorder=4)
            cx, cy = row.geometry.centroid.x, row.geometry.centroid.y
            ax.annotate(str(row["rank"]), (cx, cy),
                        fontsize=7, ha="center", va="center",
                        color="white", fontweight="bold", zorder=5)

        # Colourbar for rank
        sm = ScalarMappable(cmap="autumn_r",
                            norm=mcolors.Normalize(vmin=1, vmax=n))
        sm.set_array([])
        cbar2 = plt.colorbar(sm, ax=ax, fraction=0.025, pad=0.06)
        cbar2.set_label("Site rank (1 = best)")
        cbar2.set_ticks([1, n//2, n])

        label = "Healthcare" if model_name == "healthcare" else "Agriculture"
        ax.set_title(
            f"Top {n} {label} Candidate Sites\n"
            f"14 Rural LGAs, Oyo State, Nigeria",
            fontsize=13, fontweight="bold", pad=12)
        ax.set_xlabel("Easting (m, UTM Zone 31N)", fontsize=9)
        ax.set_ylabel("Northing (m, UTM Zone 31N)", fontsize=9)
        ax.tick_params(labelsize=8)

        plt.tight_layout()
        out = OUT_M / f"{model_name}_candidate_sites_map.png"
        fig.savefig(out, dpi=200, bbox_inches="tight")
        plt.close()
        print(f"  [OK  ] Map saved: {out.name}")

    except Exception as e:
        print(f"  [WARN] Map failed: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",
                        choices=["healthcare","agriculture","both"],
                        default="both")
    args = parser.parse_args()

    models = (["healthcare","agriculture"] if args.model == "both"
              else [args.model])

    for m in models:
        ok = run_ranking(m)
        if not ok:
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Site ranking complete for: {', '.join(models)}")
    print(f"  GeoPackages saved to    : outputs/vectors/")
    print(f"  Maps saved to           : outputs/maps/")
    print(f"  Next: python src/run_reports.py --model both")
    print(f"{'='*60}\n")
