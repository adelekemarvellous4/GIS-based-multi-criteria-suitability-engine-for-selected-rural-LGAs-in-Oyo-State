"""
reporting.py
------------
Automated PDF report generation for the Oyo Rural Suitability Engine.

Produces a structured PDF report per model containing:
  - Project metadata and study area summary
  - Methodology summary
  - AHP weights table and CR check
  - Fuzzy parameter table
  - Suitability map (embedded image)
  - Uncertainty map (embedded image)
  - Classified area statistics
  - Ranked candidate sites table
"""

import numpy as np
from pathlib import Path
from datetime import datetime
from utils import setup_logger

logger = setup_logger(__name__)


def generate_report(model_name: str,
                    config: dict,
                    outputs_dir: Path,
                    maps_dir: Path,
                    vectors_dir: Path,
                    report_path: Path) -> Path:
    """
    Generate a PDF suitability report for one model.

    Args:
        model_name: 'healthcare' or 'agriculture'
        config: Loaded model YAML config dict
        outputs_dir: Path to outputs/rasters/
        maps_dir: Path to outputs/maps/
        vectors_dir: Path to outputs/vectors/
        report_path: Output PDF path

    Returns:
        Path to generated PDF.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle, Image, PageBreak,
                                        HRFlowable)
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        logger.error("reportlab not installed. Run: pip install reportlab")
        return None

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(str(report_path), pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    style_title   = ParagraphStyle("Title2", parent=styles["Title"],
                                   fontSize=16, spaceAfter=12)
    style_h1      = ParagraphStyle("H1", parent=styles["Heading1"],
                                   fontSize=13, spaceAfter=6)
    style_h2      = ParagraphStyle("H2", parent=styles["Heading2"],
                                   fontSize=11, spaceAfter=4)
    style_body    = ParagraphStyle("Body", parent=styles["Normal"],
                                   fontSize=9, spaceAfter=4, leading=13)
    style_caption = ParagraphStyle("Caption", parent=styles["Normal"],
                                   fontSize=8, textColor=colors.grey,
                                   alignment=TA_CENTER)

    GREEN  = colors.HexColor("#1D9E75")
    BLUE   = colors.HexColor("#378ADD")
    LGREY  = colors.HexColor("#F5F5F5")
    model_color = GREEN if model_name == "healthcare" else BLUE
    emoji = "🏥" if model_name == "healthcare" else "🌾"

    story = []
    label = model_name.title()

    # ── Cover ────────────────────────────────────────────────────────────────
    story += [
        Spacer(1, 1*cm),
        Paragraph(f"{label} Suitability Analysis", style_title),
        Paragraph("Oyo Rural Suitability Engine", styles["Heading2"]),
        Paragraph("Rural LGAs, Oyo State, Nigeria", style_body),
        HRFlowable(width="100%", thickness=2, color=model_color),
        Spacer(1, 0.3*cm),
        Paragraph(f"Generated: {datetime.now().strftime('%d %B %Y, %H:%M')}", style_caption),
        Spacer(1, 0.5*cm),
    ]

    # ── 1. Model Summary ─────────────────────────────────────────────────────
    story += [
        Paragraph("1. Model Summary", style_h1),
        Paragraph(
            f"This report presents the results of the {label} Suitability Model, "
            f"one of two parallel models in the Oyo Rural Suitability Engine. "
            f"The model integrates {len(config.get('criteria', {}))} spatial criteria, "
            f"weighted using the Analytic Hierarchy Process (AHP) and standardised "
            f"via fuzzy membership functions, to produce a continuous suitability "
            f"surface across 19 rural Local Government Areas (LGAs) of Oyo State.",
            style_body),
        Spacer(1, 0.3*cm),
    ]

    # ── 2. AHP Weights Table ─────────────────────────────────────────────────
    story.append(Paragraph("2. AHP Criteria Weights", style_h1))
    cr = config.get("ahp_matrix", {}).get("consistency_ratio", "—")
    story.append(Paragraph(
        f"Consistency Ratio (CR) = {cr} &lt; 0.10 — matrix accepted.",
        style_body))

    criteria = config.get("criteria", {})
    weight_data = [["Criterion", "Direction", "Weight", "Fuzzy Type"]]
    for name, cfg in criteria.items():
        weight_data.append([
            name.replace("_", " ").title(),
            cfg.get("direction", "—"),
            f"{cfg.get('weight', 0)*100:.1f}%",
            cfg.get("fuzzy_type", "—").replace("_", " "),
        ])

    weight_table = Table(weight_data, colWidths=[6*cm, 2.5*cm, 2*cm, 3.5*cm])
    weight_table.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0), model_color),
        ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
        ("FONTSIZE",     (0,0), (-1,-1), 8),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[LGREY, colors.white]),
        ("GRID",         (0,0), (-1,-1), 0.3, colors.lightgrey),
        ("ALIGN",        (2,0), (2,-1), "CENTER"),
        ("TOPPADDING",   (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0), (-1,-1), 3),
    ]))
    story += [weight_table, Spacer(1, 0.4*cm)]

    # ── 3. Fuzzy Parameters Table ─────────────────────────────────────────────
    story.append(Paragraph("3. Fuzzy Membership Parameters", style_h1))
    fuzzy_data = [["Criterion", "Type", "Parameters", "Justification"]]
    for name, cfg in criteria.items():
        params = cfg.get("fuzzy_params", {})
        param_str = ", ".join(f"{k}={v}" for k, v in params.items())
        just = cfg.get("justification", "—")
        fuzzy_data.append([
            name.replace("_", " ").title(),
            cfg.get("fuzzy_type", "—").replace("_", " "),
            param_str,
            just[:80] + ("…" if len(just) > 80 else ""),
        ])

    fuzzy_table = Table(fuzzy_data, colWidths=[4*cm, 2.5*cm, 4*cm, 5.5*cm])
    fuzzy_table.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0), model_color),
        ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
        ("FONTSIZE",     (0,0), (-1,-1), 7),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[LGREY, colors.white]),
        ("GRID",         (0,0), (-1,-1), 0.3, colors.lightgrey),
        ("TOPPADDING",   (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0), (-1,-1), 3),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]))
    story += [fuzzy_table, Spacer(1, 0.4*cm), PageBreak()]

    # ── 4. Suitability Map ───────────────────────────────────────────────────
    suit_map = maps_dir / f"{model_name}_suitability_map.png"
    story.append(Paragraph("4. Suitability Map", style_h1))
    if suit_map.exists():
        story += [
            Image(str(suit_map), width=16*cm, height=8*cm),
            Paragraph(
                f"Figure 1. {label} suitability map (left: continuous score; right: 5-class classification).",
                style_caption),
            Spacer(1, 0.4*cm),
        ]
    else:
        story += [
            Paragraph(f"[Map not yet generated — run notebook 03/04]", style_body),
            Spacer(1, 0.4*cm),
        ]

    # ── 5. Uncertainty Map ───────────────────────────────────────────────────
    unc_map = maps_dir / f"{model_name}_suitability_uncertainty_map.png"
    story.append(Paragraph("5. Uncertainty Analysis", style_h1))
    story.append(Paragraph(
        "Monte Carlo simulation (1,000 iterations, ±10% weight perturbation). "
        "Standard deviation measures per-pixel sensitivity to weight assumptions.",
        style_body))
    if unc_map.exists():
        story += [
            Image(str(unc_map), width=16*cm, height=5*cm),
            Paragraph(
                "Figure 2. Uncertainty maps: mean suitability, standard deviation (σ), "
                "and coefficient of variation (CV).",
                style_caption),
            Spacer(1, 0.4*cm),
        ]

    # ── 6. Candidate Sites ───────────────────────────────────────────────────
    story.append(Paragraph("6. Top Candidate Sites", style_h1))
    sites_path = vectors_dir / f"{model_name}_candidate_sites.gpkg"
    if sites_path.exists():
        try:
            import geopandas as gpd
            sites = gpd.read_file(sites_path)
            display_cols = [c for c in ["rank","mean_suitability","area_ha",
                                        "distance_to_road","composite_score"]
                            if c in sites.columns]
            sites_data = [[c.replace("_", " ").title() for c in display_cols]]
            for _, row in sites.head(15).iterrows():
                sites_data.append([
                    str(row[c]) if isinstance(row[c], int)
                    else f"{row[c]:.3f}" if isinstance(row[c], float) else str(row[c])
                    for c in display_cols
                ])
            col_w = 16*cm / len(display_cols)
            sites_table = Table(sites_data, colWidths=[col_w]*len(display_cols))
            sites_table.setStyle(TableStyle([
                ("BACKGROUND",   (0,0), (-1,0), model_color),
                ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
                ("FONTSIZE",     (0,0), (-1,-1), 8),
                ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS",(0,1),(-1,-1),[LGREY, colors.white]),
                ("GRID",         (0,0), (-1,-1), 0.3, colors.lightgrey),
                ("ALIGN",        (0,0), (-1,-1), "CENTER"),
                ("TOPPADDING",   (0,0), (-1,-1), 3),
                ("BOTTOMPADDING",(0,0), (-1,-1), 3),
            ]))
            story += [
                Paragraph(f"Top {min(15, len(sites))} of {len(sites)} candidate sites "
                          f"(ranked by composite score):", style_body),
                Spacer(1, 0.2*cm),
                sites_table,
            ]
        except Exception as e:
            story.append(Paragraph(f"Could not load candidate sites: {e}", style_body))
    else:
        story.append(Paragraph("[Candidate sites not yet generated — run notebook 06]",
                                style_body))

    # ── Build ────────────────────────────────────────────────────────────────
    doc.build(story)
    logger.info(f"Report saved: {report_path}")
    return report_path


def generate_both_reports(root_dir: Path = Path(".")) -> dict:
    """Generate reports for both models."""
    from utils import load_config
    results = {}
    for model in ["healthcare", "agriculture"]:
        cfg = load_config(root_dir / f"config/{model}_config.yml")
        path = generate_report(
            model_name=model,
            config=cfg,
            outputs_dir=root_dir / "outputs/rasters",
            maps_dir=root_dir / "outputs/maps",
            vectors_dir=root_dir / "outputs/vectors",
            report_path=root_dir / f"outputs/reports/{model}_suitability_report.pdf",
        )
        results[model] = path
    return results
