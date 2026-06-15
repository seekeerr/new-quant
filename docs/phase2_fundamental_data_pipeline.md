# Phase 2 — Point-in-Time Fundamental Data Pipeline for India

**Status:** Research & implementation plan. No backtests, no parameter tuning, no new factors.
**Goal:** Build an institutional-grade, survivorship-free, look-ahead-free fundamental dataset
that can later support Quality, Value, Profitability, Momentum+Quality, Momentum+Value, and
multi-factor strategies — bolted onto the existing survivorship-free **price spine**
(3,290 ISIN-keyed equities from daily bhavcopy, `data/cache_bhav/`).

> Design principle that governs everything below: **bitemporal storage**. Every fact has a
> *valid-time* (the fiscal period it describes) and a *knowledge-time* (the moment it became
> public on the exchange). A backtest at date `T` may only read facts whose knowledge-time ≤ `T`.
> Nothing is ever overwritten; revisions are appended as new versions.

---

## 0. How this connects to Phase 1

We already have:
- A survivorship-free **price spine**: per-day NSE bhavcopy → wide panels, including delisted names.
- A stable security identity lesson: **ISIN is the key, not the ticker** (521 symbols carried ≥2 ISINs over time; 488 non-equity instruments were purged via ISIN prefix).
- A corporate-action gap-detector (to be *replaced* by a proper actions table here).
- An equity whitelist (`symbols_equity.txt`) and the `symbol_isin.csv` mapping.

The fundamental layer **attaches to this spine by `company_id`/`isin`**, never by raw ticker.

---

## 1. Data Sources

The honest summary up front: **only paid institutional databases give true PIT +
survivorship-free India fundamentals out of the box.** Every free *retail* source
(Screener, Tickertape, MoneyControl) shows a **current, restated, survivors-only** view —
useful as a cross-check, fatal as a primary PIT source. The correct free route is to build
PIT yourself from **NSE/BSE primary filings**, which are timestamped at announcement.

### 1A. Paid / institutional

| Source | Cost (India) | Coverage | Reliability | History | PIT support | API |
|---|---|---|---|---|---|---|
| **CMIE Prowess / ProwessDx** | ~₹1–5L/yr (academic far cheaper) | ~50k cos incl. **unlisted + delisted** | Very high — as-reported **and** standardized | 1989/90– | **Yes** — result/announcement dates + vintages | Yes (ProwessIQ/DX export, queries) |
| **Capitaline (Accord Fintech)** | ~₹50k–2L/yr | ~40k cos, **delisted retained** | High | mid-1990s– | Partial→Yes (result dates) | Yes (Capitaline Plus, data feed) |
| **Ace Equity (Accord)** | ~₹30k–1L/yr | ~5k+ listed | High | mid-1990s– | Partial (result dates) | Yes (Excel plug-in / feed) |
| **Refinitiv / LSEG (Worldscope, Datastream)** | $10–25k+/yr | Global incl. India | Very high | 1980s– | **Yes** (true PIT + restated vintages) | Yes (Eikon/Datastream/RD libs) |
| **Bloomberg** | ~$27k/yr/seat | Global | Very high | varies | **Yes** (PIT via `BDH` overrides) | Yes (BLPAPI) |
| **S&P Capital IQ / FactSet** | $$$ institutional | Global | Very high | deep | **Yes** | Yes |
| **MCA21 (Min. of Corporate Affairs)** | ~₹100/document | **Every registered company** (listed, unlisted, struck-off) | Authoritative (audited filings) | deep | Yes (filing dates) | Limited; bulk programs |

### 1B. Free / primary (build-it-yourself PIT)

| Source | Cost | Coverage | Reliability | History | PIT support | API |
|---|---|---|---|---|---|---|
| **NSE corporate filings** (Financial Results, XBRL, Shareholding, Corp Actions, Board Meetings) | Free | All NSE-listed | High (primary) but schema drift | results ~2009 XBRL, announcements ~2015 robust | **Yes** — exchange timestamps each filing | Unofficial JSON endpoints, cookie + rate-limited |
| **BSE corporate filings / XBRL / SHP / Announcements** | Free | All BSE-listed (**wider**, more smallcaps + delisted) | High (primary) but messy | ~2001– | **Yes** — filing datetime | Unofficial JSON (`api.bseindia.com`) |
| **SEBI / company annual reports (PDF/XBRL)** | Free | Listed | Authoritative | deep | Yes (filing date) | Manual / scrape |
| **data.gov.in, RBI** | Free | Macro / aggregate | High | deep | n/a | Some APIs |

### 1C. Free / retail (cross-check only — NOT PIT)

| Source | Cost | Coverage | Reliability | History | PIT support | API |
|---|---|---|---|---|---|---|
| **Screener.in** | Free / ₹low | ~all listed | Medium-high standardized values | ~10 yr | **No** — current restated view, survivors only | Unofficial export/scrape |
| **Tickertape / Trendlyne / Tijori / StockEdge** | Free + paid | listed | Medium | varies | **No** (mostly) | Trendlyne has a paid API |
| **yfinance / Yahoo** | Free | spotty India | Low | shallow | **No** | Yes (unofficial) |

### 1D. Which fields come from where

| Field | Primary PIT source | Free-route source | Notes |
|---|---|---|---|
| Revenue, Net Profit, EPS, Operating/Net margins | Prowess / Capitaline | NSE/BSE XBRL quarterly+annual | EPS must use **PIT share count** |
| Operating Cash Flow, Free Cash Flow | Prowess / Capitaline | Annual XBRL cash-flow statement | OCF only annual for many cos; FCF = OCF − capex |
| Debt, Book Value, Total Assets/Equity | Prowess / Capitaline | XBRL balance sheet (annual; half-yearly post-LODR) | Balance sheet is **less frequent** than P&L |
| ROE, ROCE, ROA, Profitability (GP/Assets) | Derive yourself from the above | Derive | Never trust a vendor's restated ratio for PIT |
| Promoter Holding | NSE/BSE **Shareholding Pattern (SHP)** | NSE/BSE SHP (quarterly, ≤21 days post quarter-end) | Pledge % also here |
| Share count / shares outstanding | Build from corp actions + SHP + filings | NSE/BSE + corp actions | **Hardest** — drives market cap & EPS |
| Market Cap, Enterprise Value | **Compute** = price×shares(PIT); EV = MC + debt − cash | Compute | Do **not** import a vendor MC; recompute PIT |
| PE, PB | **Compute** = price ÷ PIT-EPS(ttm) / PIT-BVPS | Compute | Ratios are derived, never stored as primary |
| Quarterly / Annual results (raw) | NSE/BSE XBRL + announcement log | same | The announcement log is the PIT backbone |

**Recommendation for this project (budget-aware):**
1. **If you can get CMIE Prowess** (individual/academic) — do that; it is the India institutional standard and gives PIT + delisted in one shot. Lowest build risk.
2. **Otherwise build the free PIT pipeline from BSE+NSE XBRL filings**, keyed to the existing ISIN spine, cross-validated against Screener for the *standardized* values (not as truth, as a sanity bound). Start with **quality metrics only** (Section 8 explains why).

---

## 2. Survivorship Bias — keeping the dead in the data

The dataset must include every company that **ever** traded, regardless of later fate.

1. **Anchor to the survivorship-free price spine.** The universe of `company_id`s is defined by
   the bhavcopy history (every ISIN that ever traded EQ), not by any "current constituents" list.
   This already includes 1,261 delisted names.
2. **Delisted / bankrupt:** keep all historical rows; set `securities.status='DELISTED'` and a
   `delisting_date`. Fundamentals up to the last filing remain. Record a **delisting return** /
   recovery value in `corporate_actions` (don't silently drop to NaN — that was a Phase-1 gap).
3. **Merged / acquired (target):** the acquired company keeps all its history; mark
   `status='MERGED'`, store the acquirer `company_id` and effective date in a `mergers` table.
   Its fundamentals **do not move** to the acquirer.
4. **Acquirer / surviving entity:** its share count and balance sheet **step-change** at the
   merger effective date — captured via `corporate_actions` + `shares_outstanding`, never by
   back-filling the acquirer's pre-merger statements with combined figures.
5. **No future leakage in the universe itself:** index/universe membership is stored with
   `from_date`/`to_date` (Section 4). A name that joined NIFTY 500 in 2020 must not be a member
   in a 2015 query.
6. **Free-source trap:** Screener/Tickertape silently exclude delisted/merged names and restate
   survivors. Using them as a primary source **re-introduces** survivorship bias. They are
   cross-checks only.

---

## 3. Point-in-Time Alignment (the look-ahead rule)

The single most important rule. Worked example, exactly as asked:

> Q1-FY21 results (period-end **30-Jun-2020**) are announced to the exchange on **15-Aug-2020**.
> A rebalance on **01-Jul-2020** must use the company's **previously** available report
> (Q4-FY20, announced ~Jun-2020), **never** the 15-Aug figures.

### Implementation

- Store three dates on every report:
  - `period_end_date` — the fiscal period (valid-time).
  - `announcement_datetime` — the **exchange timestamp** when the filing went public (knowledge-time). This is the gatekeeper.
  - `ingestion_timestamp` — when *we* fetched it (audit only).
- **Accessor contract** — the only sanctioned way to read fundamentals in a backtest:
  ```
  as_of(company_id, T):
      return latest report R for company_id
             where R.announcement_datetime <= T - SAFETY_LAG
             order by announcement_datetime desc, version desc
             limit 1
  ```
  - `SAFETY_LAG` (e.g., **1 trading day**) models "published at the close, tradable next day".
    Apply it as a fixed policy, not a tunable parameter.
- **Use announcement date, not period-end + a guessed offset.** Indian reporting lags vary
  (SEBI LODR: quarterly within 45 days of quarter-end, annual audited within 60 days), and
  companies often file late. A fixed "+45d" assumption leaks for early filers and lags for late
  filers. Always use the real timestamp.
- **Vintaging / restatements (transaction-time):** audited numbers, restatements, and
  re-classifications arrive later. Store each as a new `version` with its own
  `announcement_datetime`. `as_of(T)` therefore returns the figure **as it was known at T**,
  including the original (possibly later-corrected) value. Never overwrite.
- **TTM construction is also PIT:** a trailing-twelve-month EPS/sales at date `T` must be
  assembled only from quarters whose `announcement_datetime ≤ T`. If the most recent 4 quarters
  weren't all public by `T`, use the most recent 4 that *were*.
- **PIT market cap / valuation ratios:** `market_cap(T) = price(T) × shares_outstanding_as_of(T)`,
  where shares come from the step series. PE/PB at `T` = `price(T) ÷ PIT-EPS_ttm(T)` /
  `÷ PIT-BVPS(T)`. Never import a vendor's ratio.
- **Unit test the leakage boundary** (Section 7): assert `as_of` never returns a row with
  `announcement_datetime > T`.

---

## 4. Database Design (bitemporal, PostgreSQL-style DDL sketch)

Identity flows **company_id → security_id → symbol/isin over time**. One company can own several
securities (face-value changes, DVR class); one security can wear several tickers over time.

```sql
-- ── MASTERS ───────────────────────────────────────────────────────────
CREATE TABLE companies (
    company_id      BIGSERIAL PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    sector          TEXT, industry TEXT,
    incorporation_date DATE,
    status          TEXT,             -- ACTIVE | DELISTED | MERGED | SUSPENDED
    primary_cin     TEXT              -- MCA corporate identity number (stable)
);

CREATE TABLE securities (
    security_id     BIGSERIAL PRIMARY KEY,
    company_id      BIGINT NOT NULL REFERENCES companies(company_id),
    instrument_type TEXT NOT NULL,    -- EQ | DVR | ETF | INVIT | REIT ...
    listing_date    DATE, delisting_date DATE,
    status          TEXT
);

-- ISIN can change (face-value split) → keep a history, not a single column
CREATE TABLE isin_history (
    security_id BIGINT REFERENCES securities(security_id),
    isin        CHAR(12) NOT NULL,
    valid_from  DATE NOT NULL, valid_to DATE,        -- NULL = current
    PRIMARY KEY (security_id, isin, valid_from)
);
CREATE INDEX ix_isin ON isin_history(isin);

-- Ticker renames over time
CREATE TABLE symbol_history (
    security_id BIGINT REFERENCES securities(security_id),
    exchange    TEXT NOT NULL,        -- NSE | BSE
    symbol      TEXT NOT NULL,
    valid_from  DATE NOT NULL, valid_to DATE,
    PRIMARY KEY (security_id, exchange, symbol, valid_from)
);
CREATE INDEX ix_symbol ON symbol_history(exchange, symbol);

-- ── PRICES (reuse Phase-1 spine) ──────────────────────────────────────
CREATE TABLE prices (
    security_id BIGINT REFERENCES securities(security_id),
    d           DATE NOT NULL,
    open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
    volume BIGINT, turnover NUMERIC,
    adj_close NUMERIC,                -- split/bonus-adjusted (Section 6)
    PRIMARY KEY (security_id, d)
);
CREATE INDEX ix_prices_date ON prices(d);

-- ── CORPORATE ACTIONS ─────────────────────────────────────────────────
CREATE TABLE corporate_actions (
    action_id   BIGSERIAL PRIMARY KEY,
    security_id BIGINT REFERENCES securities(security_id),
    action_type TEXT NOT NULL,        -- SPLIT|BONUS|RIGHTS|DIVIDEND|MERGER|DEMERGER|SPINOFF|DELIST|BUYBACK
    announcement_datetime TIMESTAMPTZ,-- knowledge-time
    ex_date     DATE, record_date DATE,
    ratio_num   NUMERIC, ratio_den NUMERIC,   -- e.g. bonus 1:1 → 1/1; split 10→1 face
    cash_amount NUMERIC,              -- dividend / buyback price
    adj_factor  NUMERIC,              -- precomputed price-adjust factor for this event
    details     JSONB
);
CREATE INDEX ix_ca_sec_ex ON corporate_actions(security_id, ex_date);
CREATE INDEX ix_ca_ann ON corporate_actions(announcement_datetime);

-- ── SHARES OUTSTANDING (step series; drives MC & EPS) ─────────────────
CREATE TABLE shares_outstanding (
    company_id  BIGINT REFERENCES companies(company_id),
    effective_date DATE NOT NULL,     -- valid-time
    knowledge_date DATE NOT NULL,     -- when it became public
    shares      NUMERIC NOT NULL,
    source      TEXT,
    PRIMARY KEY (company_id, effective_date, knowledge_date)
);

-- ── ANNOUNCEMENTS (the PIT backbone) ──────────────────────────────────
CREATE TABLE announcements (
    announcement_id BIGSERIAL PRIMARY KEY,
    company_id  BIGINT REFERENCES companies(company_id),
    exchange    TEXT, category TEXT,  -- RESULT | SHP | BOARD_MEETING | CA | OTHER
    announcement_datetime TIMESTAMPTZ NOT NULL,
    subject     TEXT, attachment_url TEXT
);
CREATE INDEX ix_ann_co_dt ON announcements(company_id, announcement_datetime);

-- ── FUNDAMENTALS: header + line items, fully bitemporal ───────────────
CREATE TABLE financial_reports (
    report_id   BIGSERIAL PRIMARY KEY,
    company_id  BIGINT REFERENCES companies(company_id),
    period_end_date DATE NOT NULL,        -- valid-time
    period_type TEXT NOT NULL,            -- Q | H | A
    fiscal_year INT, fiscal_quarter INT,
    consolidated BOOLEAN NOT NULL,        -- standalone vs consolidated (keep both)
    announcement_datetime TIMESTAMPTZ NOT NULL,  -- knowledge-time (gatekeeper)
    version     INT NOT NULL DEFAULT 1,   -- 1=as-first-reported, 2+=restated
    is_audited  BOOLEAN, restates_report_id BIGINT,
    source      TEXT, source_url TEXT,
    ingestion_timestamp TIMESTAMPTZ DEFAULT now(),
    UNIQUE (company_id, period_end_date, period_type, consolidated, version)
);
-- The critical PIT index: "latest report known as of T"
CREATE INDEX ix_fr_pit ON financial_reports(company_id, announcement_datetime DESC, version DESC);

CREATE TABLE financial_line_items (
    report_id   BIGINT REFERENCES financial_reports(report_id),
    item_code   TEXT NOT NULL,            -- canonical: REVENUE, NET_PROFIT, OCF, TOTAL_DEBT...
    value       NUMERIC,
    PRIMARY KEY (report_id, item_code)
);

-- ── UNIVERSE / INDEX MEMBERSHIP (PIT) ─────────────────────────────────
CREATE TABLE index_constituents (
    index_name  TEXT NOT NULL,            -- NIFTY 500, NIFTY 50 ...
    security_id BIGINT REFERENCES securities(security_id),
    from_date   DATE NOT NULL, to_date DATE,   -- NULL = current member
    PRIMARY KEY (index_name, security_id, from_date)
);
CREATE INDEX ix_idx_member ON index_constituents(index_name, from_date, to_date);
```

**Indexing strategy (the queries that must be fast):**
- *PIT fundamental lookup*: `(company_id, announcement_datetime DESC, version DESC)` on `financial_reports` — answers "latest report known at T" with a single index scan.
- *Price series*: PK `(security_id, d)` + `ix_prices_date`.
- *Universe at T*: `index_constituents(index_name, from_date, to_date)` range scan.
- *Identity resolution*: `ix_isin`, `ix_symbol`.
- Store **standalone and consolidated** separately; pick one consistently at read time (consolidated preferred for groups), never mix within a series.

---

## 5. Symbol Mapping (historical continuity)

Map **Symbol ↔ ISIN ↔ Company**, surviving renames, mergers, demergers.

- **Stable spine = `company_id`** (internal surrogate), with `primary_cin` (MCA CIN) as the most
  stable external anchor. ISIN is stable *within a face value*; it changes on face-value
  splits — hence `isin_history`, not a single ISIN column.
- **Renames** (e.g., `WIPRO`→ unchanged, but real cases like `Bajaj Auto`→demerged tickers,
  `MINDTREE`→merged into LTIMINDTREE): a new row in `symbol_history` with `valid_from/valid_to`;
  `company_id` unchanged. Price/fundamental series are continuous because they key on
  `security_id`/`company_id`, not the ticker string.
- **Ticker reuse** (same ticker, different company later): resolve by `(symbol, date)` against
  `symbol_history` → the *correct* `security_id` for that date. This prevents the Phase-1 risk of
  stitching two unrelated companies into one column.
- **Mergers:** `mergers(target_company_id, acquirer_company_id, effective_date, swap_ratio)`.
  Target keeps its history and is marked MERGED; acquirer's shares step at `effective_date`.
- **Demergers / spin-offs:** parent keeps history (with a value-adjustment event); child gets a
  **new** `company_id`/`security_id` listed at the demerger date. The parent's pre-demerger price
  series is adjusted by the demerger factor (Section 6); the child's series starts fresh.
- **Resolution service:** one function `resolve(symbol_or_isin, exchange, date) → security_id`,
  used by every ingest job, so identity is decided in exactly one place.

---

## 6. Corporate Actions

Each event is stored once (Section 4 table) and applied **two ways**: a **price-adjustment
factor** (for returns) and a **share-count / fundamental** effect (for per-share & MC metrics).

| Event | Price effect | Share-count / fundamental effect | PIT note |
|---|---|---|---|
| **Split** (face-value) | back-adjust pre-ex prices × (new/old) | shares ↑ by ratio; EPS/BVPS rescale | ISIN usually changes → `isin_history` |
| **Bonus** | back-adjust × den/(num+den) | shares ↑; per-share metrics rescale | detect via ratio, not gap heuristic |
| **Rights** | adjust by rights factor (incl. subscription price) | shares ↑ by subscribed amount on allotment | needs issue price + ratio |
| **Dividend** | **total-return** series adds it back; price series doesn't | reduces book value/cash | store ex-date + amount; build a TR price series separately |
| **Merger** | target series ends; acquirer continues | acquirer shares step at effective date | don't combine pre-merger statements |
| **Demerger / spin-off** | parent adjusted by demerger value factor; child starts new | parent equity ↓; child new entity | hardest to value precisely |
| **Delisting** | series ends at delisting; record exit/recovery value | mark status, record delisting return | avoids Phase-1 "exit at last price" optimism |
| **Buyback** | usually no price adjust | shares ↓ on completion | affects MC & EPS |

**Upgrade over Phase 1:** replace the overnight-gap detector with a **real corporate-actions
feed** (NSE/BSE corp-action files + Prowess/Capitaline). The gap detector missed deep ETF
splits, the TITAN 2011 split, and the CROMPGREAV demerger. Compute one canonical `adj_factor`
per event and one cumulative adjusted-price series; keep raw prices untouched. Maintain a
**separate total-return price series** so dividends are handled explicitly (Phase 1 ignored
dividends entirely).

---

## 7. Validation

Run as an automated test suite on every ingest; fail loud.

**Structural**
- *Missing values:* per (company_id, period) completeness; flag mandatory items (revenue, net profit) that are NULL.
- *Duplicates:* unique `(company_id, period_end, period_type, consolidated, version)`; no two reports with identical key.
- *Impossible values:* shares > 0; |Assets − (Liab + Equity)| within tolerance; ROE/ROCE within sane bounds; EPS sign consistent with net-profit sign; promoter holding ∈ [0,100]; PE not computed off negative TTM EPS without a flag.

**Temporal (the ones that protect the backtest)**
- *Announcement ordering:* `announcement_datetime ≥ period_end_date + min_lag`; flag any report "known" before the period even ended (pure leakage).
- *Monotonic knowledge:* a restated version's `announcement_datetime` > the version it restates.
- *Stale data:* a name still trading but with no new quarterly result for > ~6 months → flag (possible missed filing or distress).

**Bias**
- *Survivorship leakage:* every delisted security in the price spine must have fundamentals up to (near) its delisting date; a delisted name with **no** historical fundamentals = a coverage hole, not a clean exclusion.
- *Look-ahead leakage (assertion test):* for a sample of (company, T), assert `as_of(T)` never returns `announcement_datetime > T`; and that a known result is **invisible** before its announcement and **visible** after.
- *Cross-source reconciliation:* NSE-XBRL vs BSE-XBRL vs Screener for the same (company, period) — large divergence flags a parsing or units error (₹ vs ₹ lakh vs ₹ crore is the classic bug).
- *Restatement audit:* count how often v1 (as-reported) ≠ v2 (restated); large gaps warn that using restated data would inflate backtests.

---

## 8. Final Recommendation — factor combinations ranked for India

Ranked by **(probability of a real edge in India) × (implementability given fundamental-data
quality/cost)**. Momentum and low-vol are price-only (already clean from Phase 1); the ranking
therefore turns on *how much, and how reliable, the fundamental data must be*.

**Academic backbone:**
- *Quality:* Novy-Marx (2013) gross profitability; Asness-Frazzini-Pedersen *Quality Minus Junk* (2019); Fama-French 5-factor RMW/CMA (2015). Robust in emerging markets.
- *Value & Momentum together:* Asness-Moskowitz-Pedersen *Value and Momentum Everywhere* (2013) — negatively correlated, strong combined Sharpe.
- *Low risk:* Frazzini-Pedersen *Betting Against Beta* (2014); Baker-Bradley-Wurgler low-vol anomaly.
- *India-specific:* quality and low-vol premia are comparatively persistent; pure value is cyclical; pure momentum is crash-prone (confirmed in Phase 1).

| Rank | Combination | Why | Data needed (difficulty) | India edge probability |
|---|---|---|---|---|
| **1** | **Momentum + Quality** | Best-evidenced fix for momentum crashes; quality is the **cheapest, most reliable** fundamental (ROE, margins, leverage, accruals from P&L + balance sheet). Strong EM quality premium. | Quality only — *low* (P&L + annual BS) | **High** |
| **2** | **Quality + Momentum + Low Vol** | Most defensive risk-adjusted profile; low-vol is free/price-only, so marginal extra data = just quality. Best drawdown control. | Quality only (low-vol is price) — *low–moderate* (3 moving parts) | **High** |
| **3** | **Momentum + Profitability** | Profitability (gross profit / assets, Novy-Marx) is the single most robust quality axis and trivial to compute; essentially Mom+Quality-lite with the least data. | One ratio — *very low* | **High** |
| **4** | **Momentum + Value** | Excellent academic pedigree (negative correlation → diversification), but value in India is cyclical and needs **PIT market cap + book value** (the hardest data: share-count step series). | Value — *moderate–high* (PIT MC/shares) | **Medium-High** |
| **5** | **Quality + Value** | Robust "quality at a reasonable price", but **no momentum diversifier** (forgoes the one clean signal we already have) and needs **both** quality and value data — the most build for the least incremental novelty here. | Quality **and** value — *high* | **Medium** |

**Practical build order this implies:** build the **quality** fields first (ROE, ROCE, ROA,
gross-profitability, leverage, accruals, OCF/NetProfit), keyed PIT by announcement date on the
existing ISIN spine — that alone unlocks ranks #1–#3. Defer **value** (PE/PB/EV — which depend on
the PIT share-count/market-cap machinery) to a second sprint, unlocking #4–#5. Build value/PE/PB
only after the share-count step series and PIT market-cap are validated, because that is exactly
where look-ahead and units bugs hide.

---

### One-paragraph executive summary
Build a **bitemporal** fundamental store anchored to the Phase-1 survivorship-free ISIN price
spine. Key every fact by `company_id` (not ticker), gate every read by **exchange announcement
timestamp** (not period-end), never overwrite (version restatements), and keep delisted/merged
names forever. Source truth from **NSE/BSE primary XBRL filings** (or CMIE Prowess if affordable);
use Screener/Tickertape only as cross-checks because they are restated, survivors-only views.
Validate structurally, temporally, and for both biases. Start with **quality** data to unlock
**Momentum + Quality** (the highest probability-×-implementability combination for India), and add
value/market-cap machinery only afterward.
