# Tool contracts

**What this page contains.** The contract of each of the seven **tools** the MCP server offers:
its name, parameters, description, result and errors. #6 builds the five tools not yet built to
this page word for word ([0006](decisions/0006-seven-high-level-tools.md)).

**How to read it.** Read the rules for every tool first, then each tool's section. A description
in a quote block is the tool's docstring, exactly as the model sees it. An error in a code block
is the exact message, after the SDK's `Error executing tool <name>: ` prefix.

**Status.** Built (2026-10-16): `list_dates` and `get_skew` in #5, the other five in #6.

## Rules for every tool

- **Provenance.** Every result carries `date`, `snapshot` (the file name), `as_of` (15:45 New
  York with its UTC offset) and `engine_commit`.
- **Figures.** Every number is a **figure**: `{id, value, unit}`. The unit comes from the unit
  list in `CONTEXT.md`; the **figure id** follows the format there. The tool groups are `chain`,
  `skew`, `realised` (get_realised_vol), `move` (get_implied_move) and `gamma`.
- **Two kinds of "no data".** A wrong input is a tool error listing the valid values. A figure the
  engine could not compute is a normal result: its id is listed in `missing` and it is left out
  of `figures`.
- **Annotations.** Read-only and closed-world (`readOnlyHint: true`, `openWorldHint: false`).
- **Order.** Tools are registered, and so listed, in the order of this page.
- **Enums.** `kind` and `scope` are `Literal` types, so a wrong value is rejected against the
  input schema before the tool runs; the SDK writes that message.

## Errors shared by several tools

| Error | Message |
| --- | --- |
| Unknown date | `No snapshot for date {date}. Available dates: {dates}.` |
| Unknown expiry | `No expiry {expiry} on {date}. Available expiries: {expiries}.` |

`{dates}` and `{expiries}` are every valid value, in date order, joined by `, `.

## The seven tools

| # | Tool | Parameters | Figures it returns |
| --- | --- | --- | --- |
| 1 | `list_dates` | none | none; the snapshot days with provenance |
| 2 | `list_expiries` | `date` | none; the day's expiries |
| 3 | `get_chain` | `date`, `expiry`, `strikes_each_side` | quotes, IV and greeks per strike near the forward |
| 4 | `get_skew` | `date`, `expiry` | forward, ATM IV, IVs, strikes, skews, risk reversals, butterflies |
| 5 | `get_realised_vol` | `date`, `kind` | realised volatility |
| 6 | `get_implied_move` | `date`, `expiry` | implied move, ATM IV, implied-realised gap |
| 7 | `get_gamma_exposure` | `date`, `scope` | net gamma exposure, gamma flip, walls |

### 1. `list_dates()`

> List the snapshot days the other tools can answer about.
>
> Each day comes with its provenance: the snapshot file, the as-of time (15:45 New York, with its
> UTC offset) and the engine commit that built it. Call this first to find a valid `date` for the
> other tools.

- **Result.** `dates`: one entry per day, `{date, snapshot, as_of, engine_commit}`, in date order.
- **Errors.** None.

### 2. `list_expiries(date)`

> List the expiries of the SPXW chain on one snapshot day.
>
> `date` is a snapshot day from list_dates, as YYYY-MM-DD. Returns every expiry the engine
> priced that day, in date order, as YYYY-MM-DD; the first is the 0DTE expiry, which expires
> that same day. Use one of these as `expiry` in get_chain, get_skew and get_implied_move.

- **Result.** Provenance, and `expiries`: a list of dates. No figures.
- **Errors.** Unknown date.

### 3. `get_chain(date, expiry, strikes_each_side=5)`

> Get the option chain of one expiry around its forward, as of 15:45 New York.
>
> `date` is a snapshot day from list_dates; `expiry` is one of that day's expiries from
> list_expiries, both as YYYY-MM-DD. `strikes_each_side` is how many strikes to show below and
> above the forward: 5 by default, at most 15. Each strike has the call and put mid prices in
> index points, the implied volatility of its out-of-the-money side as a yearly decimal, the call
> and put delta, gamma per index point, and vega in index points per vol point. A strike with no
> usable price has its figures listed in `missing`. For skew at fixed deltas use get_skew; this
> tool does not return open interest or gamma exposure.

- **Result.** Provenance, `expiry`, `figures`, `missing`, and `note` (text or null).
- **Figures per strike.** `mid_call`, `mid_put` (`index_points`); `iv` (`decimal_vol`);
  `call_delta`, `put_delta` (`ratio`); `gamma` (`per_index_point`); `vega`
  (`index_points_per_vol_point`). Strikes are the ones nearest the expiry's forward.
- **Truncation.** Asked for more than 15, it returns 15 each side and sets `note` to:
  `Showing 15 strikes each side, the most this tool returns. Call get_chain with a smaller strikes_each_side, or use get_skew for figures at fixed deltas.`
- **Errors.** Unknown date; unknown expiry. `strikes_each_side` below 1 is rejected by the input
  schema.

### 4. `get_skew(date, expiry)`

> Get one expiry's skew figures on one snapshot day, as of 15:45 New York.
>
> `date` is a snapshot day from list_dates; `expiry` is one of that day's expiries, both as
> YYYY-MM-DD. Returns the forward, the ATM implied volatility, and at the 25, 10, 5 and 1 delta
> points the put and call IV, their strikes, each side's skew against ATM, the risk reversal (call
> IV minus put IV) and the butterfly. Delta is forward delta. IVs are yearly decimals (0.2415 is
> 24.15%); skews, risk reversals and butterflies are in vol points; the forward and strikes are in
> index points. A figure the engine could not compute is listed in `missing` by its id instead of
> being returned.

- **Result.** Provenance, `expiry`, `figures`, `missing`.
- **Figures.** `forward` (`index_points`), `atm_iv` (`decimal_vol`), and for each delta point
  `d`: `put_{d}_iv`, `call_{d}_iv` (`decimal_vol`); `put_{d}_strike`, `call_{d}_strike`
  (`index_points`); `put_{d}_skew`, `call_{d}_skew`, `risk_reversal_{d}`, `butterfly_{d}`
  (`vol_points`).
- **Errors.** Unknown date; unknown expiry.

### 5. `get_realised_vol(date, kind)`

> Get the realised volatility of the S&P 500 index on one snapshot day, up to 15:45 New York.
>
> `date` is a snapshot day from list_dates, as YYYY-MM-DD. `kind` is `since_open`: from
> five-minute index moves since the 09:30 open, adjusted by the engine's time-of-day profile of
> the past 30 sessions; or `close_to_close_20`: from the daily closes of the past 20 sessions.
> Both are yearly decimals (0.10 is 10%), the same scale as implied volatility. For implied minus
> realised volatility use get_implied_move.

- **Result.** Provenance, `kind`, `figures` (one), `missing`.
- **Figures.** `realised_vol` (`decimal_vol`).
- **Errors.** Unknown date. A wrong `kind` is rejected by the input schema.

### 6. `get_implied_move(date, expiry)`

> Get the index move one expiry's options price in, and how implied volatility compares with
> realised, as of 15:45 New York.
>
> `date` is a snapshot day from list_dates; `expiry` is one of that day's expiries, both as
> YYYY-MM-DD. Returns the implied move in index points (the move the at-the-money straddle
> prices in, up or down, by expiry), the ATM implied volatility as a yearly decimal, and the
> implied-realised gap in vol points: ATM implied volatility minus realised volatility since the
> open. A positive gap means options price in more movement than the index has shown today.

- **Result.** Provenance, `expiry`, `figures`, `missing`.
- **Figures.** `implied_move` (`index_points`), `atm_iv` (`decimal_vol`),
  `implied_realised_gap` (`vol_points`).
- **Errors.** Unknown date; unknown expiry.

### 7. `get_gamma_exposure(date, scope)`

> Get the gamma exposure of SPXW options on one snapshot day, as of 15:45 New York.
>
> `date` is a snapshot day from list_dates, as YYYY-MM-DD. `scope` is `0dte` for the options
> expiring that day only, or `all` for every expiry together. Gamma exposure is how many dollars
> of the index market makers would buy or sell for a 1% index move, from each option's gamma and
> open interest, calls above zero and puts below. Returns the net total, the index level at the
> time, the gamma flip (the index level nearest today's where the total crosses zero), and the
> walls: resistance, the strikes with the largest positive exposure, and support, the strikes
> with the most negative, strongest first. If the engine found no crossing near the index, the
> flip is listed in `missing`: there is no gamma flip in range, so a question asking for it is
> answered with cannot_answer, listing the flip as missing data. Exposure per strike is not
> returned.

- **Result.** Provenance, `scope`, `figures`, `missing`.
- **Figures.** `net_total` (`usd_per_1pct_move`); `spot`, `flip` (`index_points`);
  `resistance_1` to `resistance_4` and `support_1` to `support_4` (`index_points`), as many as
  the engine found (it names at most four each side). `resistance_1` is the call wall and
  `support_1` the put wall.
- **Errors.** Unknown date. A wrong `scope` is rejected by the input schema.
