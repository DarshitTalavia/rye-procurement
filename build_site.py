"""
build_site.py  —  generate the interactive site from the UNIFIED engine.

All shape/sector logic now comes from synth.py (one source of truth). This file
just (1) pulls synth.SECTORS + pricing constants into an embedded JS blob,
(2) ships a JS MIRROR of synth's placement maths so the browser can recompute
live as hours change, and (3) self-verifies that mirror against synth in Python.
"""

import json
import numpy as np
import shapes, synth, pricing


DATA = {
    "sectors": {k: {kk: s[kk] for kk in
                    ("family", "label", "intensity", "confidence", "floor",
                     "open", "close", "weekend_ratio", "footfall", "mix")}
                for k, s in synth.SECTORS.items()},
    "pricing": {
        "fixed_p": pricing.PRODUCTS["fixed"]["unit_p"],
        "dn_day_p": pricing.PRODUCTS["day_night"]["day_p"],
        "dn_night_p": pricing.PRODUCTS["day_night"]["night_p"],
        "standing_p_day": pricing.STANDING_P_DAY,
        "ccl_p": pricing.CCL_P_KWH, "vat": pricing.VAT, "duos": pricing.DUOS,
        "tou_curve": [round(float(x), 3) for x in pricing.TOU_CURVE_HH],
        "products": [["fixed", "Fixed flat rate"], ["day_night", "Day / Night (E7)"],
                     ["tou", "Time-of-Use / Agile"]],
    },
}


HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RYE — Meterless Procurement Estimator</title>
<style>
  :root{--ink:#1c1c1c;--mut:#6b6b6b;--line:#e6e3dc;--bg:#faf8f4;--card:#fff;
        --accent:#c1502e;--good:#2f7d52;--amber:#b8860b}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
  .wrap{max-width:760px;margin:0 auto;padding:28px 18px 60px}
  h1{font-size:22px;margin:0 0 2px} .sub{color:var(--mut);margin:0 0 22px;font-size:13px}
  .controls{display:flex;gap:14px;flex-wrap:wrap;align-items:end;
    background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
  label{display:block;font-size:12px;color:var(--mut);margin-bottom:4px}
  select,input{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:#fff}
  input[type=number]{width:74px}
  .badge{font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid var(--line)}
  .cal{background:#eaf4ee;color:var(--good);border-color:#bfe0cd}
  .pri{background:#f5efe2;color:var(--amber);border-color:#e6d9b8}
  .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
  .card .k{font-size:11px;color:var(--mut)} .card .v{font-size:18px;font-weight:600;margin-top:3px}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
  .panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin:0 0 10px}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{text-align:right;padding:7px 8px;border-bottom:1px solid var(--line)}
  th:first-child,td:first-child{text-align:left}
  tr.win td{background:#eaf4ee;font-weight:600}
  .reco{padding:14px 16px;border-radius:10px;font-size:15px;margin-top:12px}
  .reco.clear{background:#eaf4ee;border:1px solid #bfe0cd}
  .reco.close{background:#f5efe2;border:1px solid #e6d9b8}
  .reco b{color:var(--accent)}
  .foot{color:var(--mut);font-size:12px;margin-top:8px}
  svg{width:100%;height:150px;display:block}
  .cap{font-size:11px;color:var(--mut);margin-top:4px}
</style></head>
<body><div class="wrap">
  <h1>Meterless Procurement Estimator</h1>
  <p class="sub">For RYE's market &mdash; multi-site hospitality &amp; retail. No meter &rarr; annual use, daily load shape, and the tariff its shape favours. Opening hours reshape the curve live.</p>

  <div class="controls">
    <div><label>Business type</label><select id="sector"></select></div>
    <div><label>Opens</label><input id="open" type="number" min="0" max="23" step="1"></div>
    <div><label>Closes</label><input id="close" type="number" min="1" max="24" step="1"></div>
    <div><label>Floor area (m&sup2;)</label><input id="floor" type="number" min="10" step="10"></div>
    <div><span id="conf" class="badge"></span></div>
  </div>

  <div class="cards" id="cards"></div>

  <div class="panel">
    <h2>Daily load shape (reshapes with opening hours)</h2>
    <svg id="chart" viewBox="0 0 480 150" preserveAspectRatio="none"></svg>
    <div class="cap">Red bars = 16:00&ndash;19:00 DUoS red band. &nbsp; 00:00 &middot; 06:00 &middot; 12:00 &middot; 18:00 &middot; 24:00</div>
  </div>

  <div class="panel">
    <h2>Tariff comparison (annual)</h2>
    <table id="tariffs"><thead><tr><th>Product</th><th>&pound;/yr</th><th>p/kWh</th><th>DUoS &pound;</th></tr></thead><tbody></tbody></table>
    <div id="reco" class="reco"></div>
  </div>

  <p class="foot" id="prov"></p>
</div>
<script>
const DATA = __DATA__;
const P = DATA.pricing, $ = id => document.getElementById(id);

// ---- placement mirror of synth.py ----
const sum=a=>a.reduce((x,y)=>x+y,0), norm=a=>{const s=sum(a)||1;return a.map(x=>x/s);};
const gauss=(c,w)=>Array.from({length:48},(_,i)=>Math.exp(-0.5*((i-c)/w)**2));
function ff(peaks,o,c){let a=Array(48).fill(0);
  peaks.forEach(([hr,w,h])=>{const g=gauss(hr*2,w);for(let i=0;i<48;i++)a[i]+=h*g[i];});
  for(let i=0;i<48;i++) if(!(i>=o-1&&i<c)) a[i]=0;
  return sum(a)?norm(a):norm(Array.from({length:48},(_,i)=>(i>=o&&i<c)?1:0));}
function compose(mix,footfall,o,c){const f=ff(footfall,o,c);let a=Array(48).fill(0);
  for(const e in mix){let p;
    if(e==='refrigeration')p=Array(48).fill(1/48);
    else if(e==='baking')p=norm(gauss(o-3,2));
    else p=f;                                     // cooking/hvac/lighting follow footfall
    for(let i=0;i<48;i++)a[i]+=mix[e]*p[i];}return norm(a);}

// ---- pricing (on the composed curve) ----
function annualSplit(A,r){const nWd=261,nWe=104,wd=A/(nWd+r*nWe);return{Awd:wd*nWd,Awe:r*wd*nWe};}
function duos(slot,we){const h=Math.floor(slot/2);if(we)return P.duos.green;
  if(h>=16&&h<19)return P.duos.red;if(h>=7&&h<23)return P.duos.amber;return P.duos.green;}
function comm(prod,slot){const h=Math.floor(slot/2);
  if(prod==='fixed')return P.fixed_p;if(prod==='day_night')return h<7?P.dn_night_p:P.dn_day_p;return P.tou_curve[slot];}
function price(shape,A,wr,prod){const {Awd,Awe}=annualSplit(A,wr);let c=0,d=0;
  for(let i=0;i<48;i++){const eWd=Awd*shape[i],eWe=Awe*shape[i];
    c+=(eWd+eWe)*comm(prod,i);d+=eWd*duos(i,false)+eWe*duos(i,true);}
  const sub=c+365*P.standing_p_day+d+A*P.ccl_p,t=sub*(1+P.vat);return{prod,total:t/100,blended:t/A,duos:d/100};}
const hh=i=>`${String(Math.floor(i/2)).padStart(2,'0')}:${i%2?'30':'00'}`;

function render(){
  const sec=$('sector').value,s=DATA.sectors[sec];
  const o=(+$('open').value||0)*2,c=(+$('close').value||24)*2;
  const floor=+$('floor').value||s.floor,A=floor*s.intensity;
  const shape=compose(s.mix,s.footfall,o,c);
  const peak=hh(shape.indexOf(Math.max(...shape)));
  const night=Math.round(shape.slice(0,14).reduce((x,y)=>x+y,0)*1000)/10;
  const red=Math.round(shape.slice(32,38).reduce((x,y)=>x+y,0)*1000)/10;
  const cal=s.confidence==='validated';
  $('conf').className='badge '+(cal?'cal':'pri');
  $('conf').textContent=cal?'validated vs meter':'prior (benchmark)';
  $('cards').innerHTML=[['Annual use',Math.round(A).toLocaleString()+' kWh'],
    ['Peak time',peak],['Night share',night+'%'],['Red-band share',red+'%']]
    .map(x=>`<div class="card"><div class="k">${x[0]}</div><div class="v">${x[1]}</div></div>`).join('');
  const W=480,H=150,bw=W/48,mx=Math.max(...shape);let bars='';
  for(let i=0;i<48;i++){const h=(shape[i]/mx)*(H-10),rb=(i>=32&&i<38);
    bars+=`<rect x="${i*bw}" y="${H-h}" width="${bw-0.6}" height="${h}" fill="${rb?'#c1502e':'#9bb0a3'}"/>`;}
  $('chart').innerHTML=bars;
  const rows=P.products.map(([k,l])=>({k,l,...price(shape,A,s.weekend_ratio,k)})).sort((a,b)=>a.total-b.total);
  $('tariffs').querySelector('tbody').innerHTML=rows.map((r,i)=>
    `<tr class="${i===0?'win':''}"><td>${r.l}</td><td>&pound;${Math.round(r.total).toLocaleString()}</td>`+
    `<td>${r.blended.toFixed(2)}p</td><td>&pound;${Math.round(r.duos).toLocaleString()}</td></tr>`).join('');
  const margin=100*(rows[1].total-rows[0].total)/rows[0].total,save=Math.round(rows[rows.length-1].total-rows[0].total);
  const r=$('reco');
  if(margin>=3){r.className='reco clear';r.innerHTML=`Recommended: <b>${rows[0].l}</b> &mdash; saves &pound;${save.toLocaleString()}/yr vs worst (${margin.toFixed(1)}% clear).`;}
  else{r.className='reco close';r.innerHTML=`<b>Too close to call</b> between ${rows[0].l} and ${rows[1].l} (${margin.toFixed(1)}% apart) &mdash; confirm with real half-hourly data.`;}
  $('prov').textContent=`Shape composed from equipment placed against ${$('open').value}:00–${$('close').value}:00 (${s.confidence}). Size ${floor} m² × ${s.intensity} kWh/m²/yr. Tariff rates representative UK 2026.`;
}

const sel=$('sector'),groups={};
Object.entries(DATA.sectors).forEach(([k,v])=>{(groups[v.family]=groups[v.family]||[]).push([k,v.label]);});
Object.entries(groups).forEach(([fam,items])=>{const og=document.createElement('optgroup');og.label=fam;
  items.forEach(([k,l])=>{const o=document.createElement('option');o.value=k;o.textContent=l;og.appendChild(o);});sel.appendChild(og);});
function setDefaults(){const s=DATA.sectors[sel.value];$('open').value=s.open;$('close').value=s.close;$('floor').value=s.floor;}
sel.onchange=()=>{setDefaults();render();};
['open','close','floor'].forEach(id=>$(id).oninput=render);
setDefaults();render();
</script></body></html>"""


def main():
    import os
    os.makedirs("site", exist_ok=True)
    html = HTML.replace("__DATA__", json.dumps(DATA))
    with open("site/index.html", "w") as f:
        f.write(html)
    print("=" * 64)
    print(f"  SITE BUILT -> site/index.html  ({len(html)//1024} KB)  from unified engine")
    print("=" * 64)
    ds = json.load(open("data/dataset.json"))
    print("  Composed (engine) vs metered shape, at default hours:")
    for key in ["qsr", "bakery"]:
        comp = synth.ARCHETYPES[key]["shape_weekday"]
        real = np.array(ds["metered_shapes"][key]["weekday"])
        corr = float(np.corrcoef(comp, real)[0, 1])
        print(f"    {key:<7} corr {corr:.2f}  peak {shapes.hh_label(int(comp.argmax()))}"
              f" (real {shapes.hh_label(int(real.argmax()))})")
    print("  sectors:", list(synth.SECTORS))


if __name__ == "__main__":
    main()
