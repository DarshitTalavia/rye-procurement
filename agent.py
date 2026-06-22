"""
agent.py  —  the AI door to the meterless procurement engine.

Runs on the Claude Agent SDK, which authenticates via your Claude Code login
(a Claude Pro/Max subscription — NO API key needed). The founder runs this on
THEIR own login after `claude login`.

THE ONE RULE: the model never computes a number. It maps the business to a
preset type OR classifies its menu, calls the deterministic tools (our verified
engine), and writes the brief citing their exact figures.

Usage:
    python agent.py "I run a pub, about 200 m2, open 12pm to 11pm"
    python agent.py            # uses a built-in example
"""

import sys
import os
import json
import base64
import anyio
from claude_agent_sdk import (
    query, tool, create_sdk_mcp_server, ClaudeAgentOptions,
    AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
)
import synth, pricing, governance


# ---------------------------------------------------------------------------
# shared: turn a curve+shape into the full estimate + ranked tariffs + reco
# ---------------------------------------------------------------------------
def _analysis(curve, shape, label, confidence, annual, size_source):
    rank = pricing.compare_products(curve)
    rec = governance.recommend(curve)
    m = synth.shape_metrics_of(shape)
    products = [{"product": r["label"], "gbp_per_yr": round(r["total_gbp"]),
                 "p_per_kwh": round(r["blended_p_kwh"], 2)} for _, r in rank.iterrows()]
    return {"label": label, "confidence": confidence, "annual_kwh": round(annual),
            "size_source": size_source, "peak_time": m["peak_time"],
            "night_share_pct": m["night_pct"], "redband_share_pct": m["redband_pct"],
            "products": products, "recommended": rec["winner"],
            "runner_up": rec["runner_up"], "margin_pct": round(rec["margin_pct"], 1),
            "verdict": rec["verdict"], "saving_vs_worst_gbp": round(rec["saving_gbp"])}


# ---------------------------------------------------------------------------
# TOOLS (deterministic wrappers over the verified engine)
# ---------------------------------------------------------------------------
@tool("list_options",
      "List the known business types (with confidence) and the valid menu "
      "categories. Call this first to map the business.", {})
async def t_list(args):
    types = {k: f"{v['label']} [{v['confidence']}]" for k, v in synth.SECTORS.items()}
    cats = list(synth.DATASET["menu_to_equipment"].keys())
    return {"content": [{"type": "text", "text": json.dumps(
        {"business_types": types, "menu_categories": cats}, indent=2)}]}


@tool("analyse_type",
      "Estimate annual kWh + load shape and recommend a tariff for a KNOWN "
      "business type. Args: sector (key from list_options); optional floor_m2, "
      "open, close (hours, e.g. 11 and 23).",
      {"sector": str, "floor_m2": float, "open": float, "close": float})
async def t_type(args):
    sector = args["sector"]
    if sector not in synth.SECTORS:
        return {"content": [{"type": "text", "text": f"Unknown type '{sector}'. Call list_options."}]}
    o = args.get("open") or None
    c = args.get("close") or None
    r = synth.synthesize_year(sector, floor_m2=args.get("floor_m2") or None, open=o, close=c)
    out = _analysis(r["curve"], r["shape_weekday"], r["label"], r["confidence"],
                    r["annual_kwh"], r["size_provenance"]["source"])
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


@tool("analyse_menu",
      "Estimate + recommend for a food/drink business FROM ITS MENU (use when no "
      "preset type fits). Args: menu_categories = comma-separated values from "
      "list_options (e.g. 'fried_food,chilled_display'); optional floor_m2, open, close.",
      {"menu_categories": str, "floor_m2": float, "open": float, "close": float})
async def t_menu(args):
    cats = [c.strip() for c in args["menu_categories"].split(",") if c.strip()]
    r = synth.synthesize_from_menu(cats, floor_m2=args.get("floor_m2") or 150,
                                   open=args.get("open") or 11, close=args.get("close") or 23)
    out = _analysis(r["curve"], r["shape_weekday"], r["label"], "prior (from menu)",
                    r["annual_kwh"], r["size_source"])
    out["equipment_mix"] = {k: round(v, 2) for k, v in r["mix"].items()}
    return {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}


SYSTEM_PROMPT = """You are a procurement analyst for RYE, an energy platform for
multi-site hospitality & retail. A client gives a few facts about a site that has
NO meter data. Estimate its annual electricity use and daily load SHAPE, then
recommend the best tariff — justified by the shape, not the headline unit rate.

HARD RULES:
- Never calculate numbers yourself. Every figure must come from a tool.
- Call list_options first and map the business.
  * If it matches a known type, use analyse_type (pass floor_m2 / open / close if given).
  * If they describe a MENU (food/drink items) and no preset fits well, classify
    the items into the valid menu_categories and use analyse_menu.
  * If a MENU IMAGE is attached, read it, LIST the items you see, classify them
    into the valid menu_categories, then use analyse_menu. Echo the items you
    read in the brief so the owner can sanity-check what was detected.
- Cite the tools' exact figures. State the confidence (validated vs prior) and,
  if the verdict is "too close to call", say so — don't force a winner.

Then write a SHORT operations brief:
  1. Estimate — annual kWh + the size basis.
  2. Load shape — peak time, night share, red-band share, in plain English.
  3. Recommendation — the product, the £/yr saving vs the worst option, and WHY
     the shape drives it (high night share -> night/ToU wins; high red-band ->
     time-of-use punished by network charges).
  4. Confidence & caveats — validated vs prior; too-close-to-call; that opening
     hours/footfall are owner-provided and refine the shape.

Be concise and practical, like a brief for a busy ops team."""


_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".webp": "image/webp", ".gif": "image/gif"}

def _parse_args(argv):
    """Pull an optional --image/-i PATH; the rest is the free-text facts."""
    image, rest, i = None, [], 0
    while i < len(argv):
        if argv[i] in ("--image", "-i") and i + 1 < len(argv):
            image = argv[i + 1]; i += 2
        else:
            rest.append(argv[i]); i += 1
    return image, " ".join(rest)


def _build_prompt(facts, image):
    """No image -> plain string prompt (unchanged). With image -> streaming-input
    mode: one user message with a text block + a base64 image block."""
    if not image:
        return facts, facts
    data = base64.standard_b64encode(open(image, "rb").read()).decode()
    media = _MEDIA.get(os.path.splitext(image)[1].lower(), "image/jpeg")
    text = (facts + "\n\nA photo of the business's MENU is attached. Read it, list "
            "the food/drink items you can see, classify them into the valid "
            "menu_categories, then estimate.")

    async def stream():
        yield {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
        ]}}
    return stream(), f"{facts}  [+ menu image: {image}]"


async def main():
    server = create_sdk_mcp_server(name="rye_tools", version="2.0.0",
                                   tools=[t_list, t_type, t_menu])
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"rye_tools": server},
        allowed_tools=["mcp__rye_tools__list_options",
                       "mcp__rye_tools__analyse_type",
                       "mcp__rye_tools__analyse_menu"],
        permission_mode="bypassPermissions",
    )
    image, facts = _parse_args(sys.argv[1:])
    facts = facts or ("I run a quick-service restaurant, about 150 m2, in central "
                      "Manchester, open 11am to 11pm, seven days a week. No meter data yet.")
    prompt, shown = _build_prompt(facts, image)

    print("=" * 72 + "\nRYE METERLESS PROCUREMENT AGENT\n" + "=" * 72)
    print(f"Client: {shown}\n")

    brief = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock) and block.name.startswith("mcp__rye_tools__"):
                    print(f"  🔧 {block.name.split('__')[-1]}({block.input or ''})")
                elif isinstance(block, TextBlock):
                    print(block.text)
                    brief.append(block.text)
        elif isinstance(message, ResultMessage):
            print("\n" + "=" * 72 + "\nAgent finished.")

    with open("agent_brief.md", "w") as f:
        f.write("\n".join(brief))
    print("Saved -> agent_brief.md")


if __name__ == "__main__":
    anyio.run(main)
