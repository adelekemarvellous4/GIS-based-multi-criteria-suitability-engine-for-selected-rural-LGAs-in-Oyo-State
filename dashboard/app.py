"""
dashboard/app.py
----------------
Streamlit WebGIS Dashboard — Oyo Rural Suitability Engine

Run from project root:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

import streamlit as st
import geopandas as gpd
import rasterio
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import folium
from streamlit_folium import st_folium
from utils import load_config

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Oyo Rural Suitability Engine",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

OUT_R = ROOT_DIR / "outputs/rasters"
OUT_V = ROOT_DIR / "outputs/vectors"
OUT_M = ROOT_DIR / "outputs/maps"
INTERIM = ROOT_DIR / "data/interim"

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("🗺️ Oyo Suitability Engine")
st.sidebar.markdown("*14 Rural LGAs · Oyo State, Nigeria*")
st.sidebar.markdown("---")

model = st.sidebar.radio("Select Model", ["🏥 Healthcare", "🌾 Agriculture"])
model_name = "healthcare" if "Healthcare" in model else "agriculture"
model_color = "#1D9E75" if model_name == "healthcare" else "#2471A3"

view = st.sidebar.selectbox("View", [
    "Overview & Statistics",
    "Suitability Map",
    "Uncertainty Analysis",
    "Candidate Sites",
])

st.sidebar.markdown("---")
st.sidebar.markdown("**Data layers**")
show_boundary = st.sidebar.checkbox("Study area boundary", True)
show_sites    = st.sidebar.checkbox("Candidate sites", True)

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data
def load_suitability_stats(model_name):
    suit_path = OUT_R / f"{model_name}_suitability.tif"
    cls_path  = OUT_R / f"{model_name}_classified.tif"
    if not suit_path.exists():
        return None
    with rasterio.open(suit_path) as src:
        arr = src.read(1).astype(float)
        nd  = src.nodata
        pix_ha = abs(src.transform.a * src.transform.e) / 10_000
    arr_v = arr[(arr != nd) & ~np.isnan(arr) & (arr > 0)]
    with rasterio.open(cls_path) as src:
        cls = src.read(1)
    class_counts = {i: (cls == i).sum() for i in range(1, 6)}
    return {
        "n_pixels": len(arr_v),
        "total_ha": len(arr_v) * pix_ha,
        "mean": arr_v.mean(),
        "std": arr_v.std(),
        "min": arr_v.min(),
        "max": arr_v.max(),
        "class_counts": class_counts,
        "pix_ha": pix_ha,
    }

@st.cache_data
def load_sites(model_name):
    p = OUT_V / f"{model_name}_candidate_sites.gpkg"
    if p.exists():
        return gpd.read_file(p).to_crs("EPSG:4326")
    return None

@st.cache_data
def load_study_area():
    p = INTERIM / "study_area.gpkg"
    if p.exists():
        return gpd.read_file(p).to_crs("EPSG:4326")
    return None

# ── Header ────────────────────────────────────────────────────────────────────
icon = "🏥" if model_name == "healthcare" else "🌾"
st.title(f"{icon} {model_name.title()} Suitability Analysis")
st.markdown(f"**14 Rural LGAs · Oyo State, Nigeria** | GIS-Based MCDA | AHP-WLC")

# ── KPI Metrics ───────────────────────────────────────────────────────────────
stats = load_suitability_stats(model_name)
sites_gdf = load_sites(model_name)
study_area = load_study_area()

if stats:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total area", f"{stats['total_ha']:,.0f} ha")
    c2.metric("Mean suitability", f"{stats['mean']:.4f}")
    c3.metric("Max score", f"{stats['max']:.4f}")
    high_ha = (stats['class_counts'].get(4,0) + stats['class_counts'].get(5,0)) * stats['pix_ha']
    c4.metric("High + Very High", f"{high_ha:,.0f} ha")
    c5.metric("Top candidate sites", len(sites_gdf) if sites_gdf is not None else "—")

st.markdown("---")

# ── Views ─────────────────────────────────────────────────────────────────────

if view == "Overview & Statistics":
    col1, col2 = st.columns([1.2, 1])

    with col1:
        st.subheader("Suitability class distribution")
        if stats:
            labels = {1:"Very Low",2:"Low",3:"Moderate",4:"High",5:"Very High"}
            clrs   = ["#d73027","#fc8d59","#fee090","#91cf60","#1a9850"]
            vals   = [stats["class_counts"].get(i,0) * stats["pix_ha"]
                      for i in range(1,6)]
            fig, ax = plt.subplots(figsize=(7,4))
            bars = ax.barh([labels[i] for i in range(5,0,-1)],
                           [vals[i-1] for i in range(5,0,-1)],
                           color=[clrs[i-1] for i in range(5,0,-1)])
            ax.bar_label(bars, labels=[f"{v:,.0f} ha" for v in
                         [vals[i-1] for i in range(5,0,-1)]], padding=4, fontsize=8)
            ax.set_xlabel("Area (ha)")
            ax.spines[["top","right"]].set_visible(False)
            st.pyplot(fig)
            plt.close()

    with col2:
        st.subheader("AHP weights")
        cfg = load_config(ROOT_DIR / f"config/{model_name}_config.yml")
        crit = cfg["criteria"]
        names   = [k.replace("_"," ").replace("distance to","dist.") for k in crit]
        weights = [v["weight"] for v in crit.values()]
        fig2, ax2 = plt.subplots(figsize=(5,4))
        ax2.barh(names[::-1], weights[::-1], color=model_color, alpha=0.85)
        ax2.set_xlabel("AHP Weight")
        ax2.spines[["top","right"]].set_visible(False)
        for i, w in enumerate(weights[::-1]):
            ax2.text(w+0.002, i, f"{w*100:.1f}%", va="center", fontsize=8)
        st.pyplot(fig2)
        plt.close()

    # Sensitivity table
    st.subheader("Sensitivity analysis (single criterion removal)")
    st.markdown("Higher Δρ = removing that criterion changes results more.")
    sens_data = {
        "healthcare": {
            "distance_to_health_facility": (0.92, 0.08),
            "population_density":          (0.94, 0.06),
            "distance_to_roads":           (0.96, 0.04),
            "distance_to_settlements":     (0.97, 0.03),
            "slope":                       (0.98, 0.02),
            "land_cover_suitability":      (0.99, 0.01),
        },
        "agriculture": {
            "distance_to_water":       (0.8069, 0.1931),
            "land_cover_suitability":  (0.8919, 0.1081),
            "ndvi":                    (0.9220, 0.0770),
            "distance_to_settlements": (0.9632, 0.0368),
            "distance_to_roads":       (0.9648, 0.0352),
            "slope":                   (0.9770, 0.0230),
        }
    }
    if model_name in sens_data:
        df_sens = pd.DataFrame(
            [(k, v[0], v[1],
              "HIGH" if v[1]>0.05 else "moderate" if v[1]>0.02 else "low")
             for k,v in sorted(sens_data[model_name].items(),
                               key=lambda x: x[1][1], reverse=True)],
            columns=["Criterion removed","Spearman ρ","Δρ (impact)","Level"]
        )
        st.dataframe(df_sens, use_container_width=True, hide_index=True)


elif view == "Suitability Map":
    st.subheader("Suitability map")
    map_path = OUT_M / f"{model_name}_suitability_map.png"
    if map_path.exists():
        st.image(str(map_path), use_column_width=True,
                 caption=f"{model_name.title()} suitability — continuous (left) and classified (right)")
    else:
        st.warning("Suitability map not found. Run run_suitability.py first.")


elif view == "Uncertainty Analysis":
    st.subheader("Monte Carlo uncertainty (n=1,000, ±10% perturbation)")
    unc_map = OUT_M / f"{model_name}_uncertainty_map.png"
    if unc_map.exists():
        st.image(str(unc_map), use_column_width=True,
                 caption="Left: mean suitability | Centre: std deviation σ | Right: CV")
        st.markdown("""
        **Interpretation:**
        - **Mean suitability** — more robust than single-run result (averages out weight noise)
        - **Std deviation (σ)** — how much the score varies across 1,000 weight perturbations
        - **CV** — normalised uncertainty; CV < 0.05 = very stable; CV > 0.20 = high sensitivity
        """)
    else:
        st.warning("Uncertainty map not found. Run run_uncertainty.py first.")


elif view == "Candidate Sites":
    st.subheader(f"Top 20 candidate sites — {model_name.title()}")

    col_map, col_tbl = st.columns([1.5, 1])

    with col_map:
        # Folium interactive map
        m = folium.Map(location=[8.2, 3.5], zoom_start=8,
                       tiles="CartoDB positron")

        if study_area is not None and show_boundary:
            folium.GeoJson(
                study_area.__geo_interface__,
                style_function=lambda x: {
                    "fillColor": "transparent",
                    "color": "#666",
                    "weight": 1.5,
                    "dashArray": "5,5",
                },
                name="Study area"
            ).add_to(m)

        if sites_gdf is not None and show_sites:
            site_color = "#c0392b" if model_name == "healthcare" else "#1a5276"
            for _, row in sites_gdf.iterrows():
                folium.GeoJson(
                    row.geometry.__geo_interface__,
                    style_function=lambda x, c=site_color: {
                        "fillColor": c,
                        "color": "white",
                        "weight": 1,
                        "fillOpacity": 0.7,
                    },
                    tooltip=folium.Tooltip(
                        f"Rank: {int(row.get('rank',0))}<br>"
                        f"Score: {row.get('composite_score',0):.4f}<br>"
                        f"Mean suit.: {row.get('mean_suitability',0):.4f}<br>"
                        f"Area: {row.get('area_ha',0):.1f} ha<br>"
                        f"Dist road: {row.get('dist_to_road_m',0):.0f} m"
                    )
                ).add_to(m)

        folium.LayerControl().add_to(m)
        st_folium(m, height=450, use_container_width=True)

    with col_tbl:
        if sites_gdf is not None:
            display_cols = [c for c in
                ["rank","composite_score","mean_suitability","area_ha",
                 "dist_to_road_m","uncertainty_cv","pop_within_5km"]
                if c in sites_gdf.columns]
            df_show = sites_gdf[display_cols].copy()
            df_show.columns = [c.replace("_"," ").title() for c in display_cols]
            st.dataframe(df_show.round(4), use_container_width=True,
                         hide_index=True, height=430)
        else:
            st.warning("Candidate sites not found. Run run_site_ranking.py first.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Oyo Rural Suitability Engine · GIS-Based MCDA · AHP-WLC · "
           "14 Rural LGAs, Oyo State, Nigeria")
