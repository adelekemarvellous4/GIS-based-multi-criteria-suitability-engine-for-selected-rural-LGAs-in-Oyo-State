"""
run_uncertainty.py
------------------
Phase 8 — Monte Carlo uncertainty and sensitivity analysis.

Usage:
    python src/run_uncertainty.py --model healthcare
    python src/run_uncertainty.py --model agriculture
    python src/run_uncertainty.py --model both
"""

import sys
import argparse
import numpy as np
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

from utils import setup_logger, load_config
from uncertainty import monte_carlo_uncertainty

logger = setup_logger("uncertainty")

PROC  = ROOT_DIR / "data/processed"
OUT_R = ROOT_DIR / "outputs/rasters"
OUT_M = ROOT_DIR / "outputs/maps"

HC_STD = lambda n: PROC / f"hc_{n}_std.tif"
AG_STD = lambda n: PROC / f"ag_{n}_std.tif"


def run_uncertainty(model_name: str):
    print(f"\n{'='*60}")
    print(f"  UNCERTAINTY ANALYSIS — {model_name.upper()}")
    print(f"{'='*60}")

    cfg      = load_config(ROOT_DIR / f"config/{model_name}_config.yml")
    criteria = cfg["criteria"]
    unc_cfg  = cfg["uncertainty"]
    prefix   = "hc" if model_name == "healthcare" else "ag"
    std_fn   = HC_STD if model_name == "healthcare" else AG_STD

    # ── Check if already done ─────────────────────────────────────────────
    mean_out = OUT_R / f"{model_name}_uncertainty_mean.tif"
    std_out  = OUT_R / f"{model_name}_uncertainty_std.tif"
    cv_out   = OUT_R / f"{model_name}_uncertainty_cv.tif"

    if mean_out.exists() and std_out.exists() and cv_out.exists():
        print(f"  [SKIP] Uncertainty rasters already exist.")
        print(f"  Delete outputs/rasters/{model_name}_uncertainty_*.tif to rerun.")
        _plot_uncertainty(mean_out, std_out, cv_out, model_name)
        _print_uncertainty_stats(mean_out, std_out, cv_out)
        return True

    # ── Check standardised rasters ────────────────────────────────────────
    print(f"\n[1] Checking standardised criteria rasters...")
    std_rasters = {}
    for name in criteria:
        p = std_fn(name)
        if p.exists():
            print(f"  [OK  ] {name}")
            std_rasters[name] = p
        else:
            print(f"  [MISS] {name} — run run_suitability.py first")

    if len(std_rasters) < len(criteria):
        print(f"\n  Only {len(std_rasters)}/{len(criteria)} rasters ready.")
        print(f"  Run: python src/run_suitability.py --model {model_name}")
        return False

    # ── Run Monte Carlo ───────────────────────────────────────────────────
    n_iter  = unc_cfg.get("monte_carlo_iterations", 1000)
    perturb = unc_cfg.get("weight_perturbation_pct", 0.10)
    seed    = unc_cfg.get("seed", 42)
    weights = {name: c["weight"] for name, c in criteria.items()}
    mask_p  = OUT_R / f"{model_name}_constraint_mask.tif"

    print(f"\n[2] Monte Carlo simulation...")
    print(f"  Iterations     : {n_iter}")
    print(f"  Perturbation   : ±{perturb*100:.0f}%")
    print(f"  Seed           : {seed}")
    print(f"  Base weights   :")
    for name, w in weights.items():
        print(f"    {name:<40} {w:.4f}")

    outputs = monte_carlo_uncertainty(
        criteria_raster_paths=std_rasters,
        base_weights=weights,
        output_dir=OUT_R,
        prefix=model_name,
        n_iterations=n_iter,
        perturbation_pct=perturb,
        constraint_mask_path=mask_p if mask_p.exists() else None,
        seed=seed,
    )

    mean_out = outputs["mean"]
    std_out  = outputs["std"]
    cv_out   = outputs["cv"]

    # ── Statistics ────────────────────────────────────────────────────────
    print(f"\n[3] Uncertainty statistics...")
    _print_uncertainty_stats(mean_out, std_out, cv_out)

    # ── Sensitivity: single criterion removal ─────────────────────────────
    print(f"\n[4] Sensitivity analysis (single criterion removal)...")
    _sensitivity_analysis(std_rasters, weights, mask_p, model_name)

    # ── Map ───────────────────────────────────────────────────────────────
    print(f"\n[5] Generating uncertainty maps...")
    _plot_uncertainty(mean_out, std_out, cv_out, model_name)

    print(f"\n  Uncertainty analysis complete — {model_name}.")
    return True


def _print_uncertainty_stats(mean_path, std_path, cv_path):
    import rasterio
    stats = {}
    for label, path in [("mean",mean_path),("std",std_path),("cv",cv_path)]:
        with rasterio.open(path) as src:
            arr = src.read(1).astype(float)
            nd  = src.nodata
        arr = arr[arr != nd] if nd else arr[~np.isnan(arr)]
        arr = arr[arr > 0]
        stats[label] = arr

    print(f"  Mean suitability  : "
          f"mean={stats['mean'].mean():.4f}  std={stats['mean'].std():.4f}  "
          f"min={stats['mean'].min():.4f}  max={stats['mean'].max():.4f}")
    print(f"  Uncertainty (σ)   : "
          f"mean={stats['std'].mean():.4f}  max={stats['std'].max():.4f}")
    print(f"  Coeff. variation  : "
          f"mean={stats['cv'].mean():.4f}  max={stats['cv'].max():.4f}")

    # Stability interpretation
    mean_cv = stats['cv'].mean()
    if mean_cv < 0.05:
        interp = "Very stable — results are robust to weight changes"
    elif mean_cv < 0.10:
        interp = "Stable — minor sensitivity to weight assumptions"
    elif mean_cv < 0.20:
        interp = "Moderate sensitivity — key criteria drive results"
    else:
        interp = "High sensitivity — results depend strongly on weights"
    print(f"  Interpretation    : {interp}")


def _sensitivity_analysis(std_rasters, weights, mask_p, model_name):
    try:
        from scipy.stats import spearmanr
        from suitability_model import weighted_linear_combination
        import rasterio, tempfile, os

        base_path = OUT_R / f"{model_name}_suitability.tif"
        if not base_path.exists():
            print("  [SKIP] Base suitability raster not found")
            return

        with rasterio.open(base_path) as src:
            base = src.read(1).flatten().astype(float)
            nd   = src.nodata
        valid = (base != nd) & ~np.isnan(base) & (base > 0)

        results = []
        for drop in weights:
            reduced_w = {k: v for k, v in weights.items() if k != drop}
            total = sum(reduced_w.values())
            reduced_w = {k: v/total for k, v in reduced_w.items()}
            reduced_r = {k: v for k, v in std_rasters.items() if k != drop}

            tmp = OUT_R / f"_tmp_sens_{drop}.tif"
            try:
                weighted_linear_combination(
                    reduced_r, reduced_w, tmp,
                    mask_p if mask_p.exists() else None)
                with rasterio.open(tmp) as src:
                    alt = src.read(1).flatten().astype(float)
                both = valid & ~np.isnan(alt) & (alt > 0)
                rho, _ = spearmanr(base[both], alt[both])
                results.append((drop, round(rho, 4), round(1-rho, 4)))
            except Exception as e:
                results.append((drop, 0, 1))
            finally:
                if tmp.exists(): tmp.unlink()

        results.sort(key=lambda x: x[2], reverse=True)
        print(f"  {'Criterion removed':<42} {'Spearman ρ':>12} {'Δρ (impact)':>12}")
        print(f"  {'-'*42} {'-'*12} {'-'*12}")
        for name, rho, delta in results:
            impact = "HIGH" if delta > 0.05 else "moderate" if delta > 0.02 else "low"
            print(f"  {name:<42} {rho:>12.4f} {delta:>10.4f}  {impact}")
        print(f"\n  Higher Δρ = removing that criterion changes results more.")

    except ImportError:
        print("  [SKIP] scipy not available for sensitivity analysis")
    except Exception as e:
        print(f"  [WARN] Sensitivity analysis error: {e}")


def _plot_uncertainty(mean_path, std_path, cv_path, model_name):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import rasterio

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        cmap_suit = "RdYlGn" if model_name == "healthcare" else "YlGn"

        configs = [
            (mean_path, "Mean suitability",         cmap_suit,  0, 1),
            (std_path,  "Std deviation (σ)",         "Oranges",  0, None),
            (cv_path,   "Coeff. of variation (CV)",  "Reds",     0, None),
        ]

        for ax, (path, title, cmap, vmin, vmax) in zip(axes, configs):
            with rasterio.open(path) as src:
                arr = src.read(1).astype(float)
                nd  = src.nodata
                ext = [src.bounds.left, src.bounds.right,
                       src.bounds.bottom, src.bounds.top]
            arr_m = np.where((arr == nd) | (arr <= 0), np.nan, arr)
            kw = dict(cmap=cmap, vmin=vmin, extent=ext, origin="upper")
            if vmax: kw["vmax"] = vmax
            im = ax.imshow(arr_m, **kw)
            ax.set_title(title, fontsize=11)
            ax.set_xlabel("Easting (m)", fontsize=8)
            ax.tick_params(labelsize=7)
            plt.colorbar(im, ax=ax, fraction=0.03)

        label = "Healthcare" if model_name == "healthcare" else "Agriculture"
        plt.suptitle(
            f"{label} — Monte Carlo Uncertainty (n=1000, ±10% weight perturbation)\n"
            f"14 Rural LGAs, Oyo State, Nigeria",
            fontsize=12, fontweight="bold")
        plt.tight_layout()

        out = OUT_M / f"{model_name}_uncertainty_map.png"
        fig.savefig(out, dpi=200, bbox_inches="tight")
        plt.close()
        print(f"  [OK  ] Map saved: {out.name}")

    except Exception as e:
        print(f"  [WARN] Map generation failed: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["healthcare","agriculture","both"],
                        default="both")
    args = parser.parse_args()

    models = (["healthcare","agriculture"] if args.model == "both"
              else [args.model])

    for m in models:
        ok = run_uncertainty(m)
        if not ok:
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Uncertainty analysis complete for: {', '.join(models)}")
    print(f"  Next: python src/run_site_ranking.py --model both")
    print(f"{'='*60}\n")
