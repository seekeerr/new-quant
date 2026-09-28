"""
THE FROZEN STRATEGY. Do not tune these numbers.

Every parameter here was selected on 2012-2021 data and then validated once on
2022-2026, which had never been touched. That single clean out-of-sample test is
the only reason the 30% figure means anything. Every edit to this file spends a
little of that credibility: change a number, and the holdout result no longer
describes the strategy you are running.

If you want to try a variant, add it as a NEW entry in VARIANTS below and let the
tracker record both. Do not edit FROZEN in place.

Validated record (see STRATEGY_CAMPAIGN_RESULTS.md):
    discovery 2012-2021 (searched) : 26.77% CAGR, Sharpe 1.27
    holdout   2022-2026 (clean)    : 30.08% CAGR, Sharpe 1.32, MaxDD -16.2%
    champion  holdout              : 16.90%
    NIFTY 500 TRI                  : 13.63%
    capacity                       : 23.64% CAGR still at Rs 50 crore
"""
import hashlib
import json

FROZEN = {
    'name': 'Mom+LowVol+Amihud',
    'version': '1.0.0',
    'frozen_on': '2026-09-22',

    # signal weights - must sum to 1.0
    'w_momentum': 0.375,
    'w_lowvol': 0.375,
    'w_amihud': 0.25,

    # signal lookbacks (trading days)
    'mom_formation': 252,
    'mom_skip': 21,
    'vol_lookback': 252,
    'amihud_lookback': 60,

    # portfolio construction
    'n_stocks': 10,
    'buffer': 20,              # hold until rank falls past this
    'rebalance': 'monthly',
    'rank_band': (0, 500),     # top-500 by turnover
    'weighting': 'equal',

    # risk
    'stop_loss': None,         # tested; it reduced returns
    'max_position_pct': 0.10,
}

# Variants you may be tracking alongside the frozen strategy. These are NOT
# validated to the same standard - they are here so the tracker can compare.
VARIANTS = {
    'frozen': FROZEN,
    'n5_concentrated': {**FROZEN, 'name': 'Mom+LowVol+Amihud n5',
                        'n_stocks': 5, 'buffer': 10, 'version': 'var-n5'},
    'n20_diversified': {**FROZEN, 'name': 'Mom+LowVol+Amihud n20',
                        'n_stocks': 20, 'buffer': 40, 'version': 'var-n20'},
}

BENCHMARKS = {
    'nifty500_tri': 0.1363,
    'champion_holdout': 0.1690,
    'strategy_holdout': 0.3008,
}


def param_hash(cfg=None):
    """Fingerprint of the parameter set, so drift is detectable."""
    c = dict(cfg or FROZEN)
    c.pop('name', None)
    payload = json.dumps(c, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def build_scorer(cfg=None):
    """Construct the ranking function from a (frozen) parameter set."""
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import signals as S
    from research_harness import load_panels

    c = cfg or FROZEN
    _, _, _, _, turn = load_panels()
    return S.blend([
        (S.momentum(c['mom_formation'], c['mom_skip']), c['w_momentum']),
        (S.low_vol(c['vol_lookback']), c['w_lowvol']),
        (S.amihud(c['amihud_lookback'])(turn), c['w_amihud']),
    ])


if __name__ == '__main__':
    print(f"{FROZEN['name']} v{FROZEN['version']}  hash={param_hash()}")
    for k, v in FROZEN.items():
        print(f'  {k:<18} {v}')
