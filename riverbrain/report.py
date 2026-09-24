"""Write model/fit_report.md and its figures after a fit. matplotlib is only needed here."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config as cfg

C = dict(obs="#0b0b0b", model="#2a78d6", tide="#2a78d6", bonneville="#eb6834", willamette="#1baf7a", sandy="#eda100",
         spring_neap="#4a3aa7", ocean="#e87ba4", unexplained="#8a8983", muted="#52514e", light="#c9c8c2")
TZ = "America/Los_Angeles"
plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 130, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#b5b4ae",
    "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6, "axes.axisbelow": True,
    "lines.linewidth": 1.3, "font.size": 9.5, "axes.titlesize": 10, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "legend.frameon": False, "axes.labelcolor": C["muted"],
    "xtick.color": C["muted"], "ytick.color": C["muted"],
})


def _md_table(df: pd.DataFrame, floatfmt="{:.3f}") -> str:
    cols = [df.index.name or ""] + list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for idx, row in df.iterrows():
        cells = [str(idx)] + [floatfmt.format(v) if isinstance(v, (float, np.floating)) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_report(payload, cv, cv_err, comp, inp, skill, period, wy, chosen):
    out_dir = cfg.MODEL_DIR / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. CV RMSE by model and water year
    piv = cv.pivot(index="model", columns="water_year", values="rmse_ft").loc[list(payload["cv"]["pooled_rmse_ft"])]
    piv["pooled"] = pd.Series(payload["cv"]["pooled_rmse_ft"])
    fig, ax = plt.subplots(figsize=(10, 3.8))
    y = np.arange(len(piv))[::-1]
    ax.barh(y, piv["pooled"], color=[C["model"] if m == chosen else C["light"] for m in piv.index], height=0.6)
    for yi, (m, r) in zip(y, piv.iterrows()):
        ax.text(r["pooled"] + 0.005, yi, f"{r['pooled']:.3f}", va="center", fontsize=8, color=C["muted"])
    ax.set_yticks(y, piv.index)
    ax.set_xlabel("pooled held-out RMSE, ft (leave-one-water-year-out)")
    ax.set_title("Which terms earn their place (selected model in blue)")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out_dir / "cv_models.png", bbox_inches="tight")
    plt.close(fig)

    # 2. Forecast skill vs lead
    carry = payload["forecast"]["residual_carry"]
    fig, ax = plt.subplots(figsize=(10, 3.4))
    for method, col, lab in [("baseline_noaa_plus_offset", C["light"], "NOAA tide table + today's offset"),
                             ("resid_tau_None", C["unexplained"], "model, no error carry"),
                             (carry, C["model"], f"model + error carry ({carry.removeprefix('resid_tau_')} h)")]:
        s = skill.loc[method]
        ax.plot(s.index, s["rmse"], color=col, lw=2, label=lab)
    ax.set(xlabel="forecast lead (hours)", ylabel="RMSE, ft", title="48-hour forecast skill (held-out years)")
    ax.set_ylim(0, None)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_dir / "forecast_skill.png", bbox_inches="tight")
    plt.close(fig)

    # 3. Observed vs model, all years (daily means) and daily residual range
    daily = comp[["observed", "model", "unexplained"]][period].resample("D").mean()
    fig, ax = plt.subplots(2, 1, figsize=(10, 5), sharex=True, gridspec_kw=dict(height_ratios=[2, 1]))
    ax[0].plot(daily.index.tz_convert(TZ), daily["observed"], color=C["obs"], lw=1.4, label="observed (daily mean)")
    ax[0].plot(daily.index.tz_convert(TZ), daily["model"], color=C["model"], lw=1.1, ls=(0, (4, 2)), label="model")
    ax[0].axhline(cfg.NWPS_FLOOD_STAGES_FT["action"] - 0.13, color=C["muted"], lw=0.7, ls=":")
    ax[0].text(daily.index[5].tz_convert(TZ), cfg.NWPS_FLOOD_STAGES_FT["action"] - 0.1, "NWS action stage",
               fontsize=8, color=C["muted"], va="bottom")
    ax[0].set(ylabel="stage, ft", title="Five water years: observed vs model (all-years fit)")
    ax[0].legend(loc="upper right", ncol=2)
    ax[1].plot(daily.index.tz_convert(TZ), daily["unexplained"], color=C["unexplained"], lw=1)
    ax[1].axhline(0, color=C["muted"], lw=0.6)
    ax[1].set(ylabel="ft", title="Unexplained (daily mean)")
    ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y", tz=TZ))
    fig.tight_layout()
    fig.savefig(out_dir / "five_years.png", bbox_inches="tight")
    plt.close(fig)

    # --- markdown ---
    p = payload
    sk = pd.DataFrame(p["forecast"]["skill_ft"]).T
    bs = pd.DataFrame(p["forecast"]["baseline_skill_ft"]).T
    leads = [str(h) for h in (1, 3, 6, 12, 24, 36, 48) if str(h) in sk.index]
    skill_tbl = pd.DataFrame({"model RMSE": sk.loc[leads, "rmse"], "model 5–95% error": [
        f"{sk.loc[h, 'p05']:+.2f} to {sk.loc[h, 'p95']:+.2f}" for h in leads],
        "tide-table RMSE": bs.loc[leads, "rmse"]})
    skill_tbl.index.name = "lead (h)"
    piv_md = piv.copy()
    piv_md.columns = [f"WY{c}" if c != "pooled" else "pooled" for c in piv_md.columns]
    piv_md["R² pooled"] = pd.Series(p["cv"]["pooled_r2"])
    piv_md.index.name = "model"
    band = pd.DataFrame(p["cv"]["selected_by_flow_band"]).T
    band.index.name = "Bonneville kcfs"
    phys = pd.DataFrame(p["physics"]["by_bonneville_flow"]).T
    phys.index.name = "Bonneville kcfs"
    coef = pd.DataFrame({"coefficient": pd.Series(p["coef"]),
                         "meaning": pd.Series({"const": "intercept, ft", **p["feature_doc"]})})
    coef.index.name = "term"

    md = f"""# Model fit report

*Generated by `python -m riverbrain.fit` on {p['fitted_utc']}. Do not edit by hand.*

**Selected model: {p['model_name']}**. Selection rule (declared before fitting): {p['cv']['selection_rule']}.

Training data: {p['training']['start_utc'][:10]} → {p['training']['end_utc'][:10]}
({p['training']['hours_used']:,} hours). Bonneville {p['training']['bonneville_range_kcfs'][0]}–{p['training']['bonneville_range_kcfs'][1]} kcfs,
Willamette {p['training']['willamette_range_kcfs'][0]}–{p['training']['willamette_range_kcfs'][1]} kcfs (25-h mean),
stage {p['training']['stage_range_ft'][0]}–{p['training']['stage_range_ft'][1]} ft.

## Cross-validation: leave one water year out

Each column is a water year scored by a model whose coefficients *and* lag/kernel were chosen
without that year. RMSE in ft.

{_md_table(piv_md)}

![CV by model](figures/cv_models.png)

### Selected model, held-out error by Bonneville flow

{_md_table(band)}

## Coefficients

Lag τ = {p['spec']['tau']} h, kernel width w = {p['spec']['width']} h → Bonneville centroid lag
**{p['physics']['bonneville_lag_centroid_h']:.1f} h**{f", fast-kernel lag {p['spec']['fast_tau']} h" if p['spec'].get('fast_tau') is not None else ""}{f", surge lag {p['spec']['surge_lag']} h" if 'surge' in p['coef'] else ""}.

{_md_table(coef, "{:.5f}")}

### Physical readings

{_md_table(phys)}

{"* Willamette: +10 kcfs → " + ", ".join(f"{v:+.2f} ft at {k} kcfs" for k, v in p['physics']['ft_per_10kcfs_willamette'].items()) if 'ft_per_10kcfs_willamette' in p['physics'] else ""}
{f"* Sandy River: +10 kcfs → {p['physics']['ft_per_10kcfs_sandy']:+.2f} ft" if 'ft_per_10kcfs_sandy' in p['physics'] else ""}
{f"* Spring–neap: +0.1 ft of predicted tidal envelope → {p['physics']['ft_mean_level_per_0.1ft_tidal_envelope']:+.2f} ft of mean level" if 'ft_mean_level_per_0.1ft_tidal_envelope' in p['physics'] else ""}
{f"* Astoria surge: +1 ft → {p['physics']['ft_per_ft_astoria_surge']:+.2f} ft" if 'ft_per_ft_astoria_surge' in p['physics'] else ""}

![Five years](figures/five_years.png)

## Forecast skill (hindcast)

48-h forecasts issued every 12 h through each held-out year, using only data available at
the forecast origin. Future Bonneville and Willamette flows are held at their last value; the
tide comes from predictions. The model's current error is carried forward using the option
that minimized mean RMSE across leads: **{p['forecast']['residual_carry']}** (mean RMSE by option:
{", ".join(f"{k} {v:.3f}" for k, v in p['forecast']['mean_rmse_by_method_ft'].items())}).

{_md_table(skill_tbl)}

The comparison baseline is {p['forecast']['baseline_note']}.

![Forecast skill](figures/forecast_skill.png)

## Diagnostics

* Tide terms computed on the live run's ~50-day window vs the full record, max abs difference at
  "now" over 20 random times: {p['diagnostics']['tide_terms_window_edge_max_abs_diff']} (ft).
* Bonneville QC flags over the training period: {p['diagnostics']['bonneville_qc_flags']}.
* Dataquery vs CDA max difference where both have data: {p['diagnostics']['dataquery_vs_cda_max_abs_diff_kcfs']} kcfs.
"""
    (cfg.MODEL_DIR / "fit_report.md").write_text(md, encoding="utf-8")
