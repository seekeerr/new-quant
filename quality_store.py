"""
QUALITY STORE — Stage-1 Momentum + Quality pilot (frozen-engine, drop-in scorer).

The ONLY new data dependency the pilot introduces. It reads the single hand-filled
file `data/cache_fundamentals/pilot_fundamentals.csv` and exposes a point-in-time
(PIT) accessor plus two drop-in ranking scorers, matching the exact signature every
Phase-1 factor used:  `scorer(close_panel, date, universe) -> Series sorted best->worst`.

It does NOT fetch anything, scrape anything, or build a database. No network. The CSV
is the single source of truth and stays empty (verified=FALSE) until a human fills it.

Quality metrics (Novy-Marx gross profitability + ROE), derived here, never imported:
    gross_profitability = gross_profit / total_assets
    roe                 = net_profit  / total_equity

PIT (look-ahead) rule — the gatekeeper
--------------------------------------
A backtest at date T may only read a report whose *knowledge date* <= T - SAFETY_LAG.
    knowledge_date = filing_date            (preferred: the real announcement date)
                   = period_end + REPORTING_LAG_DAYS   (fallback when filing_date blank)
We NEVER read by period_end alone (that leaks: the FY2020 number is not public on
2020-03-31). The fallback lag is a conservative fixed policy, not a tunable parameter.
Only rows with verified == TRUE are ever used (the Phase-1 data-hygiene gate).
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
FUND_CSV = PROJECT_ROOT / "data" / "cache_fundamentals" / "pilot_fundamentals.csv"

# Conservative fixed PIT policy (see module docstring). Indian annual audited results
# are due within 60 days of FY-end but many file late; 120 days (>3 months, the
# PHASE1_DECISION minimum) keeps us safely on the public side without throwing away a
# whole year of signal. A real `filing_date` in the CSV always overrides this.
REPORTING_LAG_DAYS = 120
SAFETY_LAG_DAYS = 1            # "published at close, tradable next day"
_TINY = 1e-9                   # denominator guard

# Metrics the pilot ranks on. (key -> human label)
METRICS = {
    "gross_profitability": "Gross Profitability (GP/Assets)",
    "roe": "ROE (NetInc/Equity)",
}


class QualityStore:
    """PIT-gated reader over pilot_fundamentals.csv. Empty CSV => empty store."""

    REQUIRED = ["gross_profit", "total_assets", "net_profit", "total_equity"]

    def __init__(self, csv_path: Path = FUND_CSV,
                 reporting_lag_days: int = REPORTING_LAG_DAYS,
                 safety_lag_days: int = SAFETY_LAG_DAYS,
                 require_verified: bool = True):
        self.csv_path = Path(csv_path)
        self.reporting_lag = pd.Timedelta(days=reporting_lag_days)
        self.safety_lag = pd.Timedelta(days=safety_lag_days)
        self.require_verified = require_verified
        self.raw = self._load_raw()          # every row, parsed (for diagnostics)
        self.usable = self._build_usable()    # verified + computable metrics, PIT-keyed

    # ── loading ──────────────────────────────────────────────────────
    def _load_raw(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            return pd.DataFrame()
        df = pd.read_csv(self.csv_path, dtype=str)
        if df.empty:
            return df
        # Numeric financials (blank -> NaN).
        num_cols = ["revenue", "cogs", "gross_profit", "net_profit",
                    "total_assets", "total_equity", "total_debt", "ocf"]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df["period_end"] = pd.to_datetime(df.get("period_end"), errors="coerce")
        df["filing_date"] = pd.to_datetime(df.get("filing_date"), errors="coerce")
        df["verified_bool"] = (df.get("verified", "FALSE").astype(str)
                               .str.strip().str.upper() == "TRUE")
        # gross_profit may be left blank but derivable from revenue - cogs.
        derivable = df["gross_profit"].isna() & df["revenue"].notna() & df["cogs"].notna()
        df.loc[derivable, "gross_profit"] = df.loc[derivable, "revenue"] - df.loc[derivable, "cogs"]
        # knowledge_date: real filing date, else conservative period_end + lag.
        df["knowledge_date"] = df["filing_date"]
        fallback = df["knowledge_date"].isna() & df["period_end"].notna()
        df.loc[fallback, "knowledge_date"] = df.loc[fallback, "period_end"] + self.reporting_lag
        # Derived metrics (guarded denominators).
        df["gross_profitability"] = _safe_div(df["gross_profit"], df["total_assets"])
        df["roe"] = _safe_div(df["net_profit"], df["total_equity"])
        return df

    def _build_usable(self) -> pd.DataFrame:
        df = self.raw
        if df.empty:
            return df
        ok = df["knowledge_date"].notna()
        if self.require_verified:
            ok &= df["verified_bool"]
        # keep rows where at least one metric is computable
        ok &= (df["gross_profitability"].notna() | df["roe"].notna())
        u = df.loc[ok, ["symbol", "isin", "fiscal_year", "period_end",
                        "knowledge_date", "gross_profitability", "roe"]].copy()
        return u.sort_values(["symbol", "knowledge_date"]).reset_index(drop=True)

    # ── PIT accessor ─────────────────────────────────────────────────
    def as_of(self, symbol: str, date: pd.Timestamp) -> dict | None:
        """Latest VERIFIED report for `symbol` known on/before `date - SAFETY_LAG`.
        Returns {gross_profitability, roe, period_end, knowledge_date} or None."""
        if self.usable.empty:
            return None
        cutoff = pd.Timestamp(date) - self.safety_lag
        rows = self.usable[(self.usable["symbol"] == symbol) &
                           (self.usable["knowledge_date"] <= cutoff)]
        if rows.empty:
            return None
        r = rows.iloc[-1]   # already sorted by knowledge_date ascending
        return {"gross_profitability": r["gross_profitability"], "roe": r["roe"],
                "period_end": r["period_end"], "knowledge_date": r["knowledge_date"]}

    def metric_panel(self, date: pd.Timestamp, universe, metric: str) -> pd.Series:
        """PIT cross-section of one metric over `universe` at `date` (covered names)."""
        if self.usable.empty:
            return pd.Series(dtype=float)
        out = {}
        for sym in universe:
            rec = self.as_of(sym, date)
            if rec is not None and pd.notna(rec.get(metric)):
                out[sym] = float(rec[metric])
        return pd.Series(out, dtype=float)

    # ── diagnostics ──────────────────────────────────────────────────
    @property
    def n_verified_rows(self) -> int:
        return int(self.usable.shape[0])

    @property
    def n_template_rows(self) -> int:
        return int(self.raw.shape[0])

    @property
    def n_companies(self) -> int:
        return int(self.raw["symbol"].nunique()) if not self.raw.empty else 0

    def coverage_at(self, date: pd.Timestamp, universe) -> dict:
        """How many universe names have PIT quality data at `date`."""
        gp = self.metric_panel(date, universe, "gross_profitability")
        roe = self.metric_panel(date, universe, "roe")
        both = set(gp.index) & set(roe.index)
        return {"universe": len(list(universe)), "gp": len(gp), "roe": len(roe),
                "both": len(both)}

    def fill_status(self) -> pd.DataFrame:
        """Per company-year filled/blank matrix (for the coverage chart / report)."""
        if self.raw.empty:
            return pd.DataFrame()
        df = self.raw.copy()
        df["has_gp"] = df["gross_profitability"].notna()
        df["has_roe"] = df["roe"].notna()
        df["filled"] = df["verified_bool"] & (df["has_gp"] | df["has_roe"])
        return df[["symbol", "fiscal_year", "has_gp", "has_roe",
                   "verified_bool", "filled"]]


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    den = den.where(den.abs() > _TINY)   # 0 / near-0 denominator -> NaN
    return num / den


# ─────────────────────────────────────────────────────────────────────
# DROP-IN SCORERS  (signature identical to every Phase-1 factor)
# ─────────────────────────────────────────────────────────────────────

def make_quality_scorer(store: QualityStore,
                        components=("gross_profitability", "roe")):
    """Variant B — Quality standalone.

    Equal-weight cross-sectional percentile of the quality components, over the names
    that have ALL components PIT-available at `date`. Higher = better. Names without
    quality data are simply not scored (the pilot's inherent coverage limit)."""
    def scorer(close_panel, date, universe):
        cols = {}
        for comp in components:
            cols[comp] = store.metric_panel(date, universe, comp)
        df = pd.DataFrame(cols).dropna(how="any")
        if len(df) < 2:
            return pd.Series(dtype=float)
        composite = df.rank(pct=True).mean(axis=1)
        return composite.sort_values(ascending=False)
    return scorer


def make_mom_lowvol_quality_scorer(store: QualityStore, w_mom, w_lowvol, w_quality,
                                   vol_lookback, components=("gross_profitability", "roe")):
    """Variant D — champion (Mom + LowVol) tilted by Quality.

    Blended rank = w_mom*mom_pctile + w_lowvol*lowvol_pctile + w_quality*quality_pctile,
    all percentiled over the SAME set of names — the intersection that has momentum,
    low-vol AND quality available. Restricting to the quality-covered subset mirrors how
    the champion's mom+lowvol blend intersects its two legs; it is the honest pilot
    behaviour (no neutral-fill of missing fundamentals)."""
    # Imported lazily so this module has no heavy import side effects.
    from run_pure_momentum import compute_12_1_momentum
    from run_momentum_lowvol import compute_realized_vol

    def scorer(close_panel, date, universe):
        mom = compute_12_1_momentum(close_panel, date, universe)
        vol = compute_realized_vol(close_panel, date, universe, vol_lookback)
        qcols = {c: store.metric_panel(date, universe, c) for c in components}
        qdf = pd.DataFrame(qcols).dropna(how="any")
        if mom.empty or vol.empty or qdf.empty:
            return pd.Series(dtype=float)
        quality = qdf.rank(pct=True).mean(axis=1)            # composite quality value
        common = mom.index.intersection(vol.index).intersection(quality.index)
        if len(common) < 2:
            return pd.Series(dtype=float)
        mom_pct = mom[common].rank(pct=True)
        lowvol_pct = (-vol[common]).rank(pct=True)
        qual_pct = quality[common].rank(pct=True)
        tot = w_mom + w_lowvol + w_quality
        blend = (w_mom * mom_pct + w_lowvol * lowvol_pct + w_quality * qual_pct) / tot
        return blend.sort_values(ascending=False)
    return scorer
