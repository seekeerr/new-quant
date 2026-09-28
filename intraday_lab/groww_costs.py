"""
Groww's actual intraday rate card, read off groww.in/pricing on 2026-09-24.

This REPLACES the earlier guess in _capital.py, which was wrong in three ways:
  - brokerage modelled at 0.03% per order; Groww charges 0.1%, capped at Rs 20,
    with a Rs 5 floor. Below Rs 20,000 per order the cap never binds, so a small
    book pays a FLAT 10 bp per leg.
  - exchange transaction charge 0.00345%; NSE is 0.00297%.
  - IPFT (Investor Protection Fund Trust) 0.0001% both sides was missing entirely.

    Brokerage    max(min(0.1% x order value, Rs 20), Rs 5)   per executed order
    STT          0.025%   SELL side only
    Stamp duty   0.003%   BUY side only
    Exchange     0.00297% both sides (NSE)
    SEBI         0.0001%  both sides
    IPFT         0.0001%  both sides (NSE)
    DP charges   Rs 0 for intraday - nothing is delivered
    GST          18% on brokerage + exchange + IPFT + SEBI

Not modelled, and worth remembering: Rs 50 per position if the system has to
auto-square-off an open intraday position. This strategy exits deliberately at
the close, so it should never pay it - but a missed exit costs Rs 50, which on
a Rs 20,000 position is 25 bp on its own.
"""
BROK_PCT, BROK_CAP, BROK_MIN = 0.001, 20.0, 5.0
STT_SELL = 0.00025
STAMP_BUY = 0.00003
EXCH = 0.0000297          # NSE
SEBI = 0.000001
IPFT = 0.000001           # NSE
GST = 0.18


def brokerage(value):
    return max(min(BROK_PCT * value, BROK_CAP), BROK_MIN)


def leg_cost(value, side):
    """Total charges for one executed order of `value` rupees. side: 'B' or 'S'."""
    brok = brokerage(value)
    exch, ipft, sebi = EXCH * value, IPFT * value, SEBI * value
    stat = STT_SELL * value if side == 'S' else STAMP_BUY * value
    gst = GST * (brok + exch + ipft + sebi)
    return brok + exch + ipft + sebi + stat + gst


def round_trip_bp(value):
    """Round-trip charges in bp of one position, EXCLUDING slippage."""
    return (leg_cost(value, 'B') + leg_cost(value, 'S')) / value * 1e4


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    print('=' * 88)
    print('  GROWW INTRADAY ROUND-TRIP COST (excl. slippage), 5-stock book')
    print('=' * 88)
    print(f'  {"capital":>12}{"per name":>12}{"brokerage":>12}{"other":>10}'
          f'{"TOTAL":>10}{"+10bp slip":>12}{"old guess":>11}')
    print('  ' + '-' * 84)
    for cap in (50_000, 100_000, 200_000, 500_000, 1_000_000, 2_500_000,
                5_000_000, 10_000_000):
        v = cap / 5
        b = 2 * brokerage(v) / v * 1e4
        tot = round_trip_bp(v)
        old = 2 * min(0.0003 * v, 20.0) / v * 1e4 + 4.7
        print(f'  {cap:>12,.0f}{v:>12,.0f}{b:>11.1f}bp{tot-b:>9.1f}bp'
              f'{tot:>9.1f}bp{tot+10:>11.1f}bp{old:>10.1f}bp')
    print('\n  Below Rs 20,000 per order the Rs 20 cap never binds, so brokerage')
    print('  is a flat 0.1% per leg = 20 bp per round trip no matter how small.')
    print('  That is the single biggest cost a Rs 1 lakh book pays.')
