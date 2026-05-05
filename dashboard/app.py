"""
dashboard/app.py
----------------
Streamlit WebGIS Dashboard — Oyo Rural Suitability Engine
Deployable on Streamlit Community Cloud (no local rasters required)

Run locally:   python -m streamlit run dashboard/app.py
Deploy:        https://share.streamlit.io
"""

import sys
from pathlib import Path
import streamlit as st
import pandas as pd
import json

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

OUT_V = ROOT_DIR / "outputs/vectors"
OUT_M = ROOT_DIR / "outputs/maps"
OUT_R = ROOT_DIR / "outputs/rasters"

try:
    from streamlit_folium import st_folium
    import folium
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

try:
    import geopandas as gpd
    HAS_GPD = True
except Exception:
    HAS_GPD = False

# ── Matplotlib theme fix (works on both light and dark Streamlit themes) ─────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({
    "text.color":        "#FFFFFF",
    "axes.labelcolor":   "#FFFFFF",
    "xtick.color":       "#FFFFFF",
    "ytick.color":       "#FFFFFF",
    "axes.edgecolor":    "#555555",
    "figure.facecolor":  "#0E1117",
    "axes.facecolor":    "#0E1117",
    "axes.titlecolor":   "#FFFFFF",
})

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Oyo Rural Suitability Engine",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Pre-computed stats (avoids loading 150MB rasters on cloud) ────────────────
STATS = {
    "healthcare": {
        "total_ha": 1_389_181,
        "mean": 0.5418,
        "std": 0.0832,
        "min": 0.2356,
        "max": 0.9223,
        "cr": 0.0140,
        "classes": {
            1: {"label":"Very Low",  "pixels":0,          "ha":0,         "pct":0.0},
            2: {"label":"Low",       "pixels":538_104,     "ha":48_430,    "pct":3.5},
            3: {"label":"Moderate",  "pixels":11_131_501,  "ha":1_001_851, "pct":72.1},
            4: {"label":"High",      "pixels":3_696_723,   "ha":332_710,   "pct":24.0},
            5: {"label":"Very High", "pixels":68_774,      "ha":6_190,     "pct":0.4},
        },
    },
    "agriculture": {
        "total_ha": 1_367_816,
        "mean": 0.5179,
        "std": 0.1138,
        "min": 0.0396,
        "max": 0.9756,
        "cr": 0.0088,
        "classes": {
            1: {"label":"Very Low",  "pixels":657,         "ha":59,        "pct":0.0},
            2: {"label":"Low",       "pixels":2_210_018,   "ha":198_905,   "pct":14.5},
            3: {"label":"Moderate",  "pixels":9_616_369,   "ha":865_487,   "pct":63.3},
            4: {"label":"High",      "pixels":3_193_958,   "ha":287_461,   "pct":21.0},
            5: {"label":"Very High", "pixels":176_720,     "ha":15_905,    "pct":1.2},
        },
    },
}

SENSITIVITY = {
    "healthcare": [
        ("distance_to_health_facility", 0.9214, 0.0786),
        ("population_density",          0.9401, 0.0599),
        ("distance_to_roads",           0.9612, 0.0388),
        ("distance_to_settlements",     0.9734, 0.0266),
        ("slope",                       0.9821, 0.0179),
        ("land_cover_suitability",      0.9903, 0.0097),
    ],
    "agriculture": [
        ("distance_to_water",       0.8069, 0.1931),
        ("land_cover_suitability",  0.8919, 0.1081),
        ("ndvi",                    0.9220, 0.0770),
        ("distance_to_settlements", 0.9632, 0.0368),
        ("distance_to_roads",       0.9648, 0.0352),
        ("slope",                   0.9770, 0.0230),
    ],
}

CRITERIA_INFO = {
    "healthcare": {
        "distance_to_health_facility": (0.2896, "Benefit", "linear increase"),
        "population_density":          (0.2433, "Benefit", "linear increase"),
        "distance_to_roads":           (0.1707, "Cost",    "linear decrease"),
        "distance_to_settlements":     (0.1125, "Cost",    "linear decrease"),
        "slope":                       (0.0919, "Cost",    "linear decrease"),
        "land_cover_suitability":      (0.0919, "Benefit", "linear increase"),
    },
    "agriculture": {
        "ndvi":                    (0.2782, "Benefit", "trapezoidal"),
        "land_cover_suitability":  (0.2075, "Benefit", "linear increase"),
        "slope":                   (0.1708, "Cost",    "linear decrease"),
        "distance_to_water":       (0.1708, "Cost",    "trapezoidal"),
        "distance_to_roads":       (0.0892, "Cost",    "linear decrease"),
        "distance_to_settlements": (0.0835, "Cost",    "trapezoidal"),
    },
}

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("🗺️ Oyo Suitability Engine")
st.sidebar.markdown("*14 Rural LGAs · Oyo State, Nigeria*")
st.sidebar.markdown("---")

model = st.sidebar.radio("Select Model", ["🏥 Healthcare", "🌾 Agriculture"])
model_name  = "healthcare" if "Healthcare" in model else "agriculture"
model_color = "#1D9E75" if model_name == "healthcare" else "#2471A3"

view = st.sidebar.selectbox("View", [
    "📊 Overview & Statistics",
    "🗺️ Suitability Map",
    "📉 Uncertainty Analysis",
    "📍 Candidate Sites",
])

st.sidebar.markdown("---")
st.sidebar.markdown("**About**")
st.sidebar.markdown(
    "GIS-Based MCDA · AHP-WLC · Monte Carlo uncertainty · "
    "14 rural LGAs · Oyo State, Nigeria")
st.sidebar.markdown(
    "[📂 GitHub Repository](https://github.com/YOUR_USERNAME/oyo-rural-suitability-engine)")

# ── Header ────────────────────────────────────────────────────────────────────
icon = "🏥" if model_name == "healthcare" else "🌾"
st.title(f"{icon} {model_name.title()} Suitability Analysis")
st.markdown(
    f"**14 Rural LGAs · Oyo State, Nigeria** &nbsp;|&nbsp; "
    f"GIS-Based MCDA &nbsp;|&nbsp; AHP-WLC &nbsp;|&nbsp; "
    f"UTM Zone 31N · 30m resolution")

# ── KPI metrics ───────────────────────────────────────────────────────────────
stats = STATS[model_name]
high_ha = stats["classes"][4]["ha"] + stats["classes"][5]["ha"]
high_pct = stats["classes"][4]["pct"] + stats["classes"][5]["pct"]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Study area", f"{stats['total_ha']:,.0f} ha")
c2.metric("Mean suitability", f"{stats['mean']:.4f}")
c3.metric("Max score", f"{stats['max']:.4f}")
c4.metric("High + Very High", f"{high_ha:,.0f} ha", f"{high_pct:.1f}% of area")
c5.metric("AHP CR", f"{stats['cr']:.4f}", "< 0.10 ✓")

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════
if "Overview" in view:

    col1, col2 = st.columns([1.2, 1])

    with col1:
        st.subheader("Suitability class distribution")
        import matplotlib.pyplot as plt
        classes = stats["classes"]
        labels  = [c["label"] for c in classes.values()]
        areas   = [c["ha"] for c in classes.values()]
        pcts    = [c["pct"] for c in classes.values()]
        colors  = ["#d73027","#fc8d59","#fee090","#91cf60","#1a9850"]

        fig, ax = plt.subplots(figsize=(7, 4))
        bars = ax.barh(labels[::-1], areas[::-1],
                       color=colors[::-1], alpha=0.88, edgecolor="white")
        for bar, pct in zip(bars, pcts[::-1]):
            ax.text(bar.get_width() + max(areas)*0.01, bar.get_y() + bar.get_height()/2,
                    f"{pct:.1f}%", va="center", fontsize=9,
                    color="#333333")
        ax.set_xlabel("Area (ha)", fontsize=9)
        ax.set_xlim(0, max(areas) * 1.18)
        ax.spines[["top","right"]].set_visible(False)
        ax.tick_params(labelsize=9)
        st.pyplot(fig)
        plt.close()

    with col2:
        st.subheader("AHP criteria weights")
        crit = CRITERIA_INFO[model_name]
        names   = [k.replace("_"," ").replace("distance to","dist.") for k in crit]
        weights = [v[0] for v in crit.values()]

        fig2, ax2 = plt.subplots(figsize=(5, 4))
        ax2.barh(names[::-1], weights[::-1], color=model_color, alpha=0.85)
        for i, w in enumerate(weights[::-1]):
            ax2.text(w + 0.003, i, f"{w*100:.1f}%", va="center", fontsize=8)
        ax2.set_xlabel("AHP Weight", fontsize=9)
        ax2.set_xlim(0, max(weights) * 1.35)
        ax2.spines[["top","right"]].set_visible(False)
        ax2.tick_params(labelsize=9)
        st.pyplot(fig2)
        plt.close()

    # Criteria table
    st.subheader("Criteria specification")
    crit_rows = []
    for name, (w, direction, fuzzy) in CRITERIA_INFO[model_name].items():
        crit_rows.append({
            "Criterion": name.replace("_"," ").title(),
            "Direction": direction,
            "Weight": f"{w*100:.1f}%",
            "Fuzzy type": fuzzy,
        })
    st.dataframe(pd.DataFrame(crit_rows), use_container_width=True, hide_index=True)

    # Sensitivity table
    st.subheader("Sensitivity analysis — single criterion removal")
    st.caption("Spearman ρ correlation between base model and model with that criterion removed. "
               "Lower ρ = higher impact.")
    sens_rows = []
    for name, rho, delta in sorted(SENSITIVITY[model_name], key=lambda x: x[2], reverse=True):
        impact = "🔴 HIGH" if delta > 0.05 else "🟡 Moderate" if delta > 0.02 else "🟢 Low"
        sens_rows.append({
            "Criterion removed": name.replace("_"," ").title(),
            "Spearman ρ": f"{rho:.4f}",
            "Δρ (impact)": f"{delta:.4f}",
            "Sensitivity level": impact,
        })
    st.dataframe(pd.DataFrame(sens_rows), use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════════════════════════
elif "Suitability Map" in view:
    st.subheader("Suitability map")
    map_path = OUT_M / f"{model_name}_suitability_map.png"
    if map_path.exists():
        st.image(str(map_path), use_container_width=True,
                 caption=f"{model_name.title()} suitability — "
                         f"continuous score (left) · classified 5 classes (right)")

        col1, col2, col3 = st.columns(3)
        col1.metric("Min score", f"{stats['min']:.4f}")
        col2.metric("Mean score", f"{stats['mean']:.4f}")
        col3.metric("Max score", f"{stats['max']:.4f}")

        st.markdown("**Class breakdown**")
        cls_rows = []
        for cls_id, info in stats["classes"].items():
            cls_rows.append({
                "Class": cls_id,
                "Label": info["label"],
                "Area (ha)": f"{info['ha']:,}",
                "% of total": f"{info['pct']:.1f}%",
            })
        st.dataframe(pd.DataFrame(cls_rows), use_container_width=True, hide_index=True)
    else:
        st.warning("Suitability map not found in outputs/maps/. "
                   "Ensure outputs/maps/ is committed to the repository.")

# ════════════════════════════════════════════════════════════════════════════
elif "Uncertainty" in view:
    st.subheader("Monte Carlo uncertainty analysis")
    st.markdown(
        "**1,000 iterations** · **±10% weight perturbation** · "
        "Welford online algorithm (memory-efficient)")

    unc_map = OUT_M / f"{model_name}_uncertainty_map.png"
    if unc_map.exists():
        st.image(str(unc_map), use_container_width=True,
                 caption="Left: mean suitability · Centre: std deviation σ · "
                         "Right: coefficient of variation CV")
    else:
        st.warning("Uncertainty map not found in outputs/maps/.")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Interpretation**")
        st.markdown("""
        - **Mean suitability** — average across 1,000 perturbed weight sets; more robust than single-run
        - **Std deviation (σ)** — per-pixel variability; high σ = sensitive to weight assumptions
        - **CV** — normalised uncertainty (σ/mean); CV < 0.05 = very stable
        """)
    with col2:
        st.markdown("**Result**")
        cv_max = 0.035 if model_name == "healthcare" else 0.020
        st.metric("Max CV observed", f"{cv_max:.3f}")
        st.metric("Stability verdict",
                  "Very stable ✓" if cv_max < 0.05 else "Stable ✓")
        st.caption("CV < 0.05 confirms results are robust to minor weight changes.")

# ════════════════════════════════════════════════════════════════════════════
elif "Candidate Sites" in view:
    st.subheader(f"Top 20 candidate sites — {model_name.title()}")

    sites_path = OUT_V / f"{model_name}_candidate_sites.gpkg"

    col_map, col_tbl = st.columns([1.5, 1])

    with col_map:
        # Always show static map first (works on cloud without geopandas)
        sites_map = OUT_M / f"{model_name}_candidate_sites_map.png"
        if sites_map.exists():
            st.image(str(sites_map), use_container_width=True,
                     caption=f"Top 20 {model_name} candidate sites "
                             f"ranked by composite score")

        # Show interactive Folium map only if all deps available
        if HAS_FOLIUM and HAS_GPD and sites_path.exists():
            st.markdown("**Interactive map** — hover/click sites for details")
            try:
                sites_gdf = gpd.read_file(sites_path).to_crs("EPSG:4326")
                m = folium.Map(location=[8.2, 3.5], zoom_start=8,
                               tiles="CartoDB positron")
                site_color = "#c0392b" if model_name == "healthcare" else "#1a5276"
                for _, row in sites_gdf.iterrows():
                    rank  = int(row.get("rank", 0))
                    score = row.get("composite_score", 0)
                    suit  = row.get("mean_suitability", 0)
                    area  = row.get("area_ha", 0)
                    road  = row.get("dist_to_road_m", 0)
                    cv    = row.get("uncertainty_cv", 0)
                    popup_html = (
                        f"<div style='font-size:12px'>"
                        f"<b>Rank {rank}</b><br>"
                        f"Score: {score:.4f}<br>"
                        f"Suitability: {suit:.4f}<br>"
                        f"Area: {area:.1f} ha<br>"
                        f"Road: {road:.0f} m<br>"
                        f"CV: {cv:.4f}</div>")
                    folium.GeoJson(
                        row.geometry.__geo_interface__,
                        style_function=lambda x, c=site_color: {
                            "fillColor":c,"color":"white",
                            "weight":1.5,"fillOpacity":0.7},
                        tooltip=f"Rank {rank} · {score:.3f}",
                        popup=folium.Popup(popup_html, max_width=200),
                    ).add_to(m)
                folium.LayerControl().add_to(m)
                st_folium(m, height=400, use_container_width=True)
            except Exception as e:
                st.caption(f"Interactive map unavailable: {e}")

    with col_tbl:
        # Load from GeoPackage if available, else show hardcoded top results
        if HAS_GPD and sites_path.exists():
            try:
                sites_gdf = gpd.read_file(sites_path)
                display_cols = [c for c in
                    ["rank","composite_score","mean_suitability","area_ha",
                     "dist_to_road_m","uncertainty_cv","pop_within_5km"]
                    if c in sites_gdf.columns]
                df_show = sites_gdf[display_cols].copy()
                rename = {
                    "rank":"Rank","composite_score":"Score",
                    "mean_suitability":"Suit.","area_ha":"Area (ha)",
                    "dist_to_road_m":"Road (m)","uncertainty_cv":"CV",
                    "pop_within_5km":"Pop 5km"
                }
                df_show = df_show.rename(columns=rename)
                for col in ["Score","Suit.","CV"]:
                    if col in df_show.columns:
                        df_show[col] = df_show[col].round(4)
                st.dataframe(df_show, use_container_width=True,
                             hide_index=True, height=460)
            except Exception as e:
                st.warning(f"Could not load sites table: {e}")
        else:
            st.info("Commit outputs/vectors/ to your GitHub repo "
                    "to display the full ranked sites table here.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Oyo Rural Suitability Engine · GIS-Based MCDA · AHP-WLC · "
    "Monte Carlo uncertainty (n=1,000) · "
    "14 Rural LGAs, Oyo State, Nigeria · 30m resolution")
