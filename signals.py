"""
Signal library for the discovery campaign.

Every signal is a factory returning a scorer:
    scorer(close_panel, date, universe) -> pd.Series sorted best-first

HARD RULE: a scorer may only read rows with index <= date. Every function here
slices `panel.loc[:date]` before touching anything. Violating that invents alpha
that cannot be traded.

Panels needed beyond close are injected at construction time (high/low/volume/
turnover), never looked up globally.
"""
import numpy as np
import pandas as pd


def _hist(panel, date, universe, min_rows=0):
    """Rows <= date, columns restricted to the tradeable universe."""
    cols = [s for s in universe if s in panel.columns]
    if not cols:
        return None
    h = panel.loc[panel.index <= date, cols]
    if len(h) < min_rows:
        return None
    return h


def _out(s):
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    return s.sort_values(ascending=False) if len(s) else pd.Series(dtype=float)


def _pct(s):
    return s.rank(pct=True)


# ── momentum family ──────────────────────────────────────────────────────

def momentum(form=252, skip=21):
    """Classic cross-sectional momentum: return over `form` days, skipping the
    most recent `skip` (the skip avoids short-term reversal)."""
    def sc(close, date, universe):
        h = _hist(close, date, universe, form + skip + 1)
        if h is None:
            return pd.Series(dtype=float)
        end = h.iloc[-(skip + 1)] if skip else h.iloc[-1]
        start = h.iloc[-(form + skip + 1)]
        return _out(end / start - 1)
    return sc


def momentum_consistency(form=252, skip=21):
    """Frog-in-the-Pan: prefer momentum delivered SMOOTHLY. Ranks on the share
    of positive days in the formation window, not the total return - a stock
    that ground higher beats one that gapped once."""
    def sc(close, date, universe):
        h = _hist(close, date, universe, form + skip + 1)
        if h is None:
            return pd.Series(dtype=float)
        w = h.iloc[-(form + skip + 1):-(skip + 1)] if skip else h.tail(form + 1)
        r = w.pct_change()
        return _out((r > 0).sum() / r.notna().sum())
    return sc


def momentum_x_consistency(form=252, skip=21, w=0.5):
    """Blend total momentum with its path quality."""
    m, c = momentum(form, skip), momentum_consistency(form, skip)
    def sc(close, date, universe):
        a, b = m(close, date, universe), c(close, date, universe)
        ix = a.index.intersection(b.index)
        if len(ix) < 2:
            return pd.Series(dtype=float)
        return _out(w * _pct(a[ix]) + (1 - w) * _pct(b[ix]))
    return sc


# ── volatility / risk family ─────────────────────────────────────────────

def low_vol(lb=252):
    def sc(close, date, universe):
        h = _hist(close, date, universe, lb + 1)
        if h is None:
            return pd.Series(dtype=float)
        return _out(-h.pct_change().tail(lb).std())
    return sc


def low_idio_vol(bench_col=None, lb=252):
    """Residual vol vs an equal-weight market proxy built from the universe
    itself (no external index needed). Low idiosyncratic vol is a documented
    anomaly distinct from low total vol."""
    def sc(close, date, universe):
        h = _hist(close, date, universe, lb + 1)
        if h is None:
            return pd.Series(dtype=float)
        r = h.pct_change().tail(lb)
        mkt = r.mean(axis=1)
        mv = mkt.var()
        if not mv or np.isnan(mv):
            return pd.Series(dtype=float)
        beta = r.apply(lambda c: c.cov(mkt) / mv)
        resid = r - np.outer(mkt.values, beta.values)
        return _out(-pd.Series(resid.std(axis=0), index=r.columns))
    return sc


def low_beta(lb=252):
    def sc(close, date, universe):
        h = _hist(close, date, universe, lb + 1)
        if h is None:
            return pd.Series(dtype=float)
        r = h.pct_change().tail(lb)
        mkt = r.mean(axis=1)
        mv = mkt.var()
        if not mv or np.isnan(mv):
            return pd.Series(dtype=float)
        return _out(-r.apply(lambda c: c.cov(mkt) / mv))
    return sc


def low_max_ret(lb=21):
    """MAX anomaly: stocks with a big single-day spike last month are
    lottery-like and underperform. Rank LOW-max highest."""
    def sc(close, date, universe):
        h = _hist(close, date, universe, lb + 1)
        if h is None:
            return pd.Series(dtype=float)
        return _out(-h.pct_change().tail(lb).max())
    return sc


def low_downside_dev(lb=252):
    def sc(close, date, universe):
        h = _hist(close, date, universe, lb + 1)
        if h is None:
            return pd.Series(dtype=float)
        r = h.pct_change().tail(lb)
        return _out(-r.where(r < 0).std())
    return sc


def range_vol(lb=60):
    """Parkinson-style vol from high/low - uses intraday range, more efficient
    than close-to-close. Needs high/low panels bound at construction."""
    def make(high, low):
        def sc(close, date, universe):
            hh, ll = _hist(high, date, universe, lb), _hist(low, date, universe, lb)
            if hh is None or ll is None:
                return pd.Series(dtype=float)
            hh, ll = hh.tail(lb), ll.tail(lb)
            pk = np.log(hh / ll) ** 2
            return _out(-np.sqrt(pk.mean() / (4 * np.log(2))))
        return sc
    return make


# ── price-location family ────────────────────────────────────────────────

def prox_52wh(lb=252):
    """George & Hwang 52-week-high proximity - documented as distinct from,
    and sometimes stronger than, plain momentum."""
    def sc(close, date, universe):
        h = _hist(close, date, universe, lb)
        if h is None:
            return pd.Series(dtype=float)
        return _out(h.iloc[-1] / h.tail(lb).max())
    return sc


def dist_from_ma(ma=200):
    def sc(close, date, universe):
        h = _hist(close, date, universe, ma + 1)
        if h is None:
            return pd.Series(dtype=float)
        return _out(h.iloc[-1] / h.tail(ma).mean() - 1)
    return sc


def reversal(lb=5):
    """Short-term reversal: recent losers bounce. Negative of recent return."""
    def sc(close, date, universe):
        h = _hist(close, date, universe, lb + 1)
        if h is None:
            return pd.Series(dtype=float)
        return _out(-(h.iloc[-1] / h.iloc[-(lb + 1)] - 1))
    return sc


# ── liquidity / participation family ─────────────────────────────────────

def amihud(lb=60):
    """Amihud illiquidity = mean(|ret| / turnover). Illiquidity premium:
    higher illiquidity has historically earned more (at the cost of capacity)."""
    def make(turn):
        def sc(close, date, universe):
            h = _hist(close, date, universe, lb + 1)
            tt = _hist(turn, date, universe, lb)
            if h is None or tt is None:
                return pd.Series(dtype=float)
            r = h.pct_change().tail(lb).abs()
            t = tt.tail(lb).replace(0, np.nan)
            return _out((r / t).mean() * 1e7)
        return sc
    return make


def turnover_trend(fast=20, slow=100):
    """Rising participation: recent turnover vs its own longer average."""
    def make(turn):
        def sc(close, date, universe):
            tt = _hist(turn, date, universe, slow)
            if tt is None:
                return pd.Series(dtype=float)
            return _out(tt.tail(fast).mean() / tt.tail(slow).mean().replace(0, np.nan))
        return sc
    return make


# ── blending ─────────────────────────────────────────────────────────────

def blend(parts):
    """parts: list of (scorer, weight). Percentile-ranks each component over the
    common set of names, so components on different scales combine sanely."""
    def sc(close, date, universe):
        acc, tot = None, 0.0
        vals = []
        for f, w in parts:
            s = f(close, date, universe)
            if len(s) < 2:
                return pd.Series(dtype=float)
            vals.append((s, w))
        ix = vals[0][0].index
        for s, _ in vals[1:]:
            ix = ix.intersection(s.index)
        if len(ix) < 2:
            return pd.Series(dtype=float)
        for s, w in vals:
            p = _pct(s[ix]) * w
            acc = p if acc is None else acc + p
            tot += w
        return _out(acc / tot)
    return sc


def veto(base, bad, frac=0.2):
    """Run `base`, then drop the worst `frac` of its picks by the `bad` signal.
    Used for quality filters layered on an existing ranking."""
    def sc(close, date, universe):
        s = base(close, date, universe)
        if len(s) < 5:
            return s
        b = bad(close, date, universe)
        ix = s.index.intersection(b.index)
        if len(ix) < 5:
            return s
        keep = _pct(b[ix]) > frac
        out = s[ix][keep]
        return out if len(out) >= 3 else s
    return sc
