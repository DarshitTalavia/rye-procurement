# RYE — Meterless Procurement Estimator

For a multi-site hospitality or retail site with **no meter data and no historical
bills**, this estimates:

1. **Annual electricity consumption**,
2. the **daily load shape** (when power is actually drawn), and
3. the **best tariff/product** — justified by the load *shape*, not the headline unit rate.

Built for RYE Case Study 1 (Agentic Procurement).

---

## The core idea

> **The load *shape* — not the unit rate — decides which tariff wins.**
> A bakery (40% of use overnight) and a QSR (peaky midday) can use the *same*
> annual kWh and the cheapest product still flips between them.

Every estimate is **one equation**: `annual kWh (SIZE) × month weights (SEASON) ×
daily rhythm (SHAPE)` → a full-year half-hourly curve, which is then priced under
each product.

The SHAPE is **composed from the business's equipment** (inferred from its type or
menu) **placed against its opening hours and footfall** — so it generalises to any
hospitality/retail site without ever metering it.

---

## Two ways to use it

### A) The site (no login, instant)
Open **`site/index.html`** — a short overview of how it works (with live-injected
validation numbers), linking to the **estimator** (`site/tool.html`): pick a
business type, set hours + size → live estimate, load-shape chart, and tariff
recommendation. Deploy the whole `site/` folder to Vercel/Netlify; self-contained.

### B) The AI agent (runs on *your* Claude login)
Turns a plain-English description (or a menu) into the brief. Uses the **Claude
Agent SDK**, which authenticates via your **Claude Pro/Max subscription — no API key**.

```bash
# 1. Install Claude Code and log in with your Claude account (one-time)
npm install -g @anthropic-ai/claude-code
claude          # then sign in (Pro or Max)

# 2. Install Python deps
pip install -r requirements.txt

# 3. Run it
python agent.py "I run a pub, about 200 m2, open 12pm to 11pm"
python agent.py "Fish & chip shop, 120 m2, open 11-9, battered fish, chips, soft drinks fridge"
python agent.py --image menu.jpg "120 m2, open 11am-9pm"   # reads a MENU PHOTO (vision)
python agent.py            # built-in example
```

The agent maps the business to a preset type, **or** classifies its menu (typed
or **from a photo**) → equipment → bespoke shape, then calls the deterministic
engine and writes the brief. With `--image`, Claude reads the menu photo via
vision (on your Claude login), echoes the items it detected, and estimates from them.

---

## How it works (the engine)

| Driver | Source |
|---|---|
| **SIZE** = floor area × intensity (kWh/m²/yr) | published CIBSE/DEC benchmarks; floor from EPC bands |
| **SHAPE** = equipment placed against hours + footfall | equipment kW from ENERGY STAR/industry; end-use split from published studies; footfall per type (Google Places in production) |
| **SEASON** = monthly weights | representative (degree-day proxy) |
| **PRICE** = bill under each product | Fixed / Day-Night / Time-of-Use + DUoS red-band + CCL + VAT (representative UK 2026 rates) |

Composition: refrigeration = 24/7 baseload; baking = pre-open; cooking/HVAC/lighting
follow the **footfall** curve, gated to opening hours.

---

## Validation — built blind, then checked against real meters

`validate_bottomup.py` builds QSR and Bakery **purely from public priors** (never
using the CSVs), then compares to the real metered data:

| | QSR | Bakery |
|---|---|---|
| Size (May kWh) | −4.1% | +5.8% |
| Tariff (the decision) | ✅ correct | ✅ correct |

→ Built blind, it gets size within ~5% and the **right tariff on both**. The decision
is robust to shape error. The two CSVs are used **only for validation**, never as inputs.

```bash
python validate_bottomup.py   # the blind held-out test
python governance.py          # fidelity + decision validation + guardrails
```

---

## File map

| File | Role |
|---|---|
| `synth.py` | **the engine** — sector presets + composition + size/season/shape |
| `pricing.py` | bill a load curve under each product |
| `governance.py` | evals (fidelity, decision) + the "too close to call" guardrail |
| `validate_bottomup.py` | the blind held-out validation |
| `shapes.py` | read the metered CSVs (build/validation only) |
| `build_dataset.py` | bake `data/dataset.json` (run once) |
| `build_site.py` | generate `site/index.html` from the engine |
| `agent.py` | the AI agent (Claude Agent SDK) |
| `data/` | the metered CSVs + baked `dataset.json` |
| `site/index.html` | the interactive calculator |

---

## Honest notes

- Tariff p/kWh are **representative UK 2026** values — real mechanism, illustrative pennies.
- QSR/Bakery are **validated** against real meters; other types are **priors** (benchmark, not yet validated) — the tool labels which is which.
- EPC floor lookup and footfall are **owner-provided / typical-per-type** here; in
  production they become the EPC register API and Google Places (Popular Times).
- The production path (`synth → pricing → governance`) never touches the CSVs.
