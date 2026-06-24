# RYE — Meterless Procurement Estimator

Most UK shops and restaurants have no smart meter. So RYE has to work out how much
electricity a site uses, when it uses it, and which tariff fits, before any reading
exists. This tool does that from a few facts about the business.

## The idea

You can't measure a site with no meter. So you build its load from what you can
see without one.

What a business uses is set by the equipment it runs and when it runs it. A fryer,
an oven, a fridge each draw power in their own pattern. So we work out the equipment,
and the equipment gives the shape. Every estimate is one equation:

```
energy = size × season × shape
```

Then we price that load under each tariff and pick the best on cost and risk.

## Run it

Two parts. The site needs no login. The agent runs on your own Claude account.

### The site (no login)

Open `site/index.html` — a short overview, with a link to the live estimator
(`site/tool.html`). Pick a business, set the hours and size, and it shows the
consumption, the load shape, and the tariff. Deploy the `site/` folder to Vercel or
Netlify for a link.

### The agent (your Claude login)

Run it on your own Claude account. No API key.

```bash
# 1. get the code
git clone https://github.com/DarshitTalavia/rye-procurement.git
cd rye-procurement

# 2. set up Claude Code (once) — sign in with your Claude account, Pro or Max
npm install -g @anthropic-ai/claude-code
claude

# 3. install Python packages (once)
pip install -r requirements.txt

# 4. run it — describe the business, or point it at a menu photo
python agent.py "Pub, 200 m2, open 12pm to 11pm"
python agent.py --image data/image.png "120 m2, open 11am to 9pm"
```

It maps the business to a type, or reads the menu (typed or from the photo), works
out the equipment, and writes the brief: annual use, load shape, and the tariff to
buy. The brief prints to the screen and saves to `agent_brief.md`. It runs on your
Claude login, so there is no API key to set up.

## How it works

- **Size**: floor area times energy per square metre (EPC and CIBSE benchmarks).
- **Season**: spreads the year across months.
- **Shape**: built from the equipment. Refrigeration runs flat. Baking is before
  open. Cooking follows footfall. Lighting and heating run across opening hours.
- **Price**: the energy in each half-hour times the price then, plus the standing
  charge, network charges, the climate levy, and VAT. Three products: flat,
  day/night, time-of-use.
- **Recommend**: cheapest on cost, then adjusted for risk. A spiky load on a
  time-varying tariff is exposed, so when the margin is thin we prefer the flat
  rate, and say why.

## How we know it works

We built the QSR and bakery estimates from public data alone, without their meters,
then compared:

- Size within ~5%.
- Shapes matched the real curves (0.79 and 0.82 correlation).
- The tool picked the same tariff the real meter would have, both times.

Run it yourself:

```bash
python validate_bottomup.py   # built blind, checked against the meters
python governance.py          # fidelity, recommendation, guardrails
```

## Files

- `synth.py` — the engine (size × season × shape).
- `pricing.py` — the bill under each product.
- `governance.py` — recommendation (cost and risk) and checks.
- `validate_bottomup.py` — the blind test.
- `build_dataset.py` — bakes the data (run once).
- `build_site.py` / `build_doc.py` — generate the tool and the overview.
- `agent.py` — the agent.
- `data/` — the metered CSVs and a sample menu image.
- `site/` — the two pages.

## Limits

Prices, footfall and EPC are fixed representative values, not live API feeds yet. In
production they connect to wholesale prices, footfall data, and the EPC register. Two
sectors are checked against real meters; the rest are benchmark estimates, and the
tool marks which is which.
