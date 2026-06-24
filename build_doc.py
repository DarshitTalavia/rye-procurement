"""
build_doc.py  —  generate the overview page (site/index.html).

The prose is fixed (plain, first-principles). The NUMBERS are injected live from
the engine so the write-up can never drift from the tool. Run after build_site.py.
"""

import json
import numpy as np
import synth, pricing, governance, shapes

DS = json.load(open("data/dataset.json"))
PC3 = synth.make_shape(0.15, [[26, 10, 1.0]])   # generic Elexon-PC3-like baseline


def corr(a, b):
    return float(np.corrcoef(a, b)[0, 1])

def blind_size_error(sector, csv, intensity, floor):
    """Blind size = public benchmark (intensity x floor); compared to the real
    May meter total. Shape-independent at the monthly level."""
    annual = intensity * floor
    shape = synth.ARCHETYPES[sector]["shape_weekday"]
    curve = synth._build_curve(shape, annual, synth.SECTORS[sector]["weekend_ratio"])
    blind_may = curve[curve["ts"].dt.month == 5]["kwh"].sum()
    real = governance.real_curve(csv)
    real_may = real[real["ts"].dt.month == 5]["kwh"].sum()
    return 100 * (blind_may - real_may) / real_may


def numbers():
    q, b = synth.ARCHETYPES["qsr"]["shape_weekday"], synth.ARCHETYPES["bakery"]["shape_weekday"]
    qr = np.array(DS["metered_shapes"]["qsr"]["weekday"])
    br = np.array(DS["metered_shapes"]["bakery"]["weekday"])
    return {
        "QSR_SIZE": f"{abs(blind_size_error('qsr', 'data/qsr_may.csv', 375, 150)):.1f}",
        "BAKERY_SIZE": f"{abs(blind_size_error('bakery', 'data/bakery_may.csv', 400, 120)):.1f}",
        "QSR_CORR": f"{corr(q, qr):.2f}",
        "BAKERY_CORR": f"{corr(b, br):.2f}",
        "BAKERY_PC3": f"{corr(PC3, br):+.2f}",
        "N_SECTORS": str(len(synth.SECTORS)),
    }


HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RYE — Meterless Procurement: how it works</title>
<style>
  :root{--ink:#1c1c1c;--mut:#6b6b6b;--line:#e6e3dc;--bg:#faf8f4;--card:#fff;--accent:#c1502e;--good:#2f7d52}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);
    font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
  .wrap{max-width:680px;margin:0 auto;padding:32px 20px 64px}
  h1{font-size:24px;margin:0 0 4px} h2{font-size:15px;margin:30px 0 8px;
     text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
  p{margin:0 0 12px} ul{margin:0 0 12px;padding-left:20px} li{margin:4px 0}
  .lede{color:var(--mut);font-size:15px;margin-bottom:18px}
  .eq{background:var(--card);border:1px solid var(--line);border-radius:10px;
      padding:12px 16px;font-size:17px;text-align:center;margin:6px 0 14px}
  .cta{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;
       padding:11px 18px;border-radius:9px;font-weight:600;margin:8px 0 4px}
  .foot{color:var(--mut);font-size:13px;border-top:1px solid var(--line);margin-top:30px;padding-top:14px}
  b{color:var(--ink)} a{color:var(--accent)}
  pre{background:#f1ede4;border:1px solid var(--line);border-radius:10px;padding:12px 14px;
      overflow-x:auto;font-size:13px;line-height:1.6;font-family:ui-monospace,Menlo,Consolas,monospace}
</style></head>
<body><div class="wrap">

<h1>Meterless procurement: how it works</h1>
<p class="lede">Most UK shops and restaurants have no smart meter. So RYE has to work out how much electricity a site uses, when it uses it, and which tariff fits, before any reading exists. This is how the tool does that from a few facts.</p>

<a class="cta" href="tool.html">Open the live estimator &rarr;</a>

<h2>The data sources</h2>
<p>You can't measure a site with no meter. So you build its load from what you can see without one.</p>
<p>What a business uses is set by the equipment it runs and when it runs it. A fryer, an oven, a fridge each draw power in their own pattern. So we don't guess by business type. We work out the equipment, and the equipment gives the shape.</p>
<p>Four things feed this:</p>
<ul>
  <li><b>Real metered curves</b> from two sites, a QSR and a bakery. We use these only to check the work, never as an input.</li>
  <li><b>Equipment</b>, read from the business type or its menu. A chip-shop menu means fryers. A bakery menu means ovens.</li>
  <li><b>Opening hours and footfall</b>, for when the place is busy.</li>
  <li><b>Public benchmarks</b>: floor area from EPC, energy per square metre from CIBSE, standard load shapes from Elexon.</li>
</ul>
<p>Only the first is measured. The rest are fixed public values.</p>

<h2>A structured way to use them</h2>
<p>Every estimate is one equation:</p>
<div class="eq">energy = size &times; season &times; shape</div>
<p>Size is floor area times energy per square metre. Season spreads the year across months. Shape is the rhythm of a day, and the shape is where the real work is.</p>
<p>We build the shape from the equipment. Refrigeration runs flat, day and night. Baking happens before the doors open. Cooking follows the footfall, at lunch and dinner. Lighting and heating run across opening hours. Add them up, weighted by how much energy each uses, and you have the daily curve. Change the hours and the curve moves.</p>

<h2>Coming to the price</h2>
<p>A bill is not one price. It is the energy used in each half-hour, times the price at that time, plus a daily standing charge, network charges, the climate levy, and VAT.</p>
<p>We rebuild that bill under three products: a flat rate, a day/night rate, and a time-of-use rate that changes every half-hour. Which is cheapest depends on when the site uses power, not on the headline unit rate. A bakery that works at night is cheap on a night rate. A restaurant that peaks at dinner is not.</p>
<p>Then we weigh risk. A spiky load on a time-varying tariff is exposed: its peaks fall when prices are high. So when the cheapest product wins only by a thin margin and the load is spiky, we recommend the flat rate instead, and say why. The reason is always the shape, never the rate.</p>

<h2>How we know it works</h2>
<p>We built the QSR and bakery estimates from public data alone, without looking at their meters. Then we compared.</p>
<p>Size came within <b>%QSR_SIZE%%</b> and <b>%BAKERY_SIZE%%</b>. The shapes matched the real curves (<b>%QSR_CORR%</b> and <b>%BAKERY_CORR%</b> correlation). And the tool picked the same tariff the real meter would have, both times.</p>
<p>We also checked against the Elexon profile, the shape the industry uses when there is no meter. Against the real bakery it scores only <b>%BAKERY_PC3%</b>; our shape scores <b>%BAKERY_CORR%</b>. The generic profile barely tracks a bakery, because it assumes business hours, not a pre-dawn bake. That is the case for building the shape from equipment instead of a generic curve.</p>

<h2>What we built</h2>
<p>Two things.</p>
<p>A <b>live tool</b>. Pick a business, set the hours and size, and it shows the consumption, the shape, and the tariff. Change the hours and the answer moves. It covers %N_SECTORS% business types across hospitality and retail.</p>
<p>An <b>agent</b>. Describe the business in plain words, or upload a photo of the menu, and it returns the same brief. It reads the menu, works out the equipment, and runs the estimate. It runs on your own Claude login, so there is no API key to manage.</p>
<p>To run the agent on your own Claude account:</p>
<pre>git clone https://github.com/DarshitTalavia/rye-procurement.git
cd rye-procurement
npm install -g @anthropic-ai/claude-code
claude            # sign in with your Claude account (Pro or Max)
pip install -r requirements.txt
python agent.py "Pub, 200 m2, open 12pm to 11pm"
python agent.py --image data/image.png "120 m2, open 11am to 9pm"</pre>
<p>The code and full instructions are in the <a href="https://github.com/DarshitTalavia/rye-procurement">repo</a>.</p>

<a class="cta" href="tool.html">Open the live estimator &rarr;</a>

<p class="foot">Prices, footfall and EPC are fixed representative values, not live API feeds yet. In production they connect to wholesale prices, footfall data, and the EPC register. Two sectors are checked against real meters; the rest are benchmark estimates, and the tool marks which is which.</p>

</div></body></html>"""


def main():
    import os
    os.makedirs("site", exist_ok=True)
    html = HTML
    for k, v in numbers().items():
        html = html.replace(f"%{k}%", v)
    with open("site/index.html", "w") as f:
        f.write(html)
    n = numbers()
    print("OVERVIEW BUILT -> site/index.html")
    print(f"  injected: QSR size ±{n['QSR_SIZE']}%, Bakery ±{n['BAKERY_SIZE']}%; "
          f"corr {n['QSR_CORR']}/{n['BAKERY_CORR']}; bakery-vs-PC3 {n['BAKERY_PC3']}; "
          f"{n['N_SECTORS']} sectors")


if __name__ == "__main__":
    main()
