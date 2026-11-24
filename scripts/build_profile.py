#!/usr/bin/env python3
"""Build the profile's SVGs from live GitHub data. Standard library only.

  GITHUB_TOKEN=... python scripts/build_profile.py

Writes assets/header.svg, assets/stats.svg and assets/cards/*.svg in the QuarkTex design system
(burnt-orange glow on near-black and warm off-white, Audiowide, Space Grotesk, Inter, JetBrains Mono).
Every number comes from the GitHub GraphQL API at build time. "Contributions" is GitHub's own count
(commits, repositories and other activity, including private work the profile shares as a count).
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

LOGIN = os.environ.get("PROFILE_LOGIN", "prasanna0070")
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
METRICS = json.loads((FONTS / "metrics.json").read_text())

ORANGE, INK0, INK1, OFF = "#E76F2A", "#0E0E0F", "#161617", "#FAF8F6"
TXT_D, BODY_D, MUTED_D = "#FFFFFF", "#D8D5D1", "#9A9A9A"
TXT_L, BODY_L, MUTED_L, BORDER_L = "#2D2D2D", "#444444", "#6E6E6E", "#E5E0DB"

MARK = ('<path d="M348.4 21.0 L534.5 21.0 L225.4 460.0 L39.3 460.0 Z"/>'
        '<path d="M522.0 255.5 L708.1 255.5 L399.0 694.5 L212.9 694.5 Z"/>'
        '<path d="M695.6 490.0 L881.7 490.0 L572.6 929.0 L386.5 929.0 Z"/>')

REPOS = {"qcobrain": ("Quarktex", "qcobrain"), "wishlabs": ("prasanna0070", "wishlabs"),
         "ivi": ("prasanna0070", "ivi-forum")}


# ---------------------------------------------------------------------------------------------- data
def gql(query: str, **variables) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}", "Content-Type": "application/json",
                 "User-Agent": "profile-builder"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    if out.get("errors"):
        raise SystemExit(f"GraphQL error: {out['errors']}")
    return out["data"]


CAL = "contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }"


def fetch() -> dict:
    d = gql(f"""query($login:String!) {{ user(login:$login) {{ createdAt
        contributionsCollection {{ contributionYears {CAL} }} }} }}""", login=LOGIN)["user"]
    last_year = d["contributionsCollection"]["contributionCalendar"]
    days: dict[str, int] = {}
    year_totals = {}
    now = dt.datetime.now(dt.timezone.utc)
    for y in d["contributionsCollection"]["contributionYears"]:
        start = dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc)
        end = min(dt.datetime(y, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
        c = gql(f"""query($login:String!, $from:DateTime!, $to:DateTime!) {{ user(login:$login) {{
            contributionsCollection(from:$from, to:$to) {{ {CAL} }} }} }}""",
                login=LOGIN, **{"from": start.isoformat(), "to": end.isoformat()})
        cal = c["user"]["contributionsCollection"]["contributionCalendar"]
        year_totals[y] = cal["totalContributions"]
        for w in cal["weeks"]:
            for day in w["contributionDays"]:
                days[day["date"]] = day["contributionCount"]
    repo_q = " ".join(
        f'{k}: repository(owner:"{o}", name:"{n}") {{ stargazerCount '
        f'defaultBranchRef {{ target {{ ... on Commit {{ history {{ totalCount }} }} }} }} }}'
        for k, (o, n) in REPOS.items())
    repos = gql(f"query {{ {repo_q} }}")
    return {"created": d["createdAt"], "last_year": last_year, "days": days, "year_totals": year_totals,
            "repos": {k: {"stars": v["stargazerCount"],
                          "commits": v["defaultBranchRef"]["target"]["history"]["totalCount"]}
                      for k, v in repos.items()}}


def streaks(days: dict[str, int], today: dt.date) -> tuple[int, int]:
    dates = sorted(days)
    longest = run = 0
    prev = None
    for s in dates:
        d = dt.date.fromisoformat(s)
        if days[s] > 0:
            run = run + 1 if prev is not None and (d - prev).days == 1 and days[prev.isoformat()] > 0 else 1
            longest = max(longest, run)
        prev = d
    cur, d = 0, today
    if days.get(d.isoformat(), 0) == 0:
        d -= dt.timedelta(days=1)          # today is not over yet
    while days.get(d.isoformat(), 0) > 0:
        cur += 1
        d -= dt.timedelta(days=1)
    return cur, longest


# ---------------------------------------------------------------------------------------------- svg kit
def face(name: str, family: str) -> str:
    b64 = base64.b64encode((FONTS / f"{name}.woff2").read_bytes()).decode()
    return f"@font-face{{font-family:'{family}';src:url(data:font/woff2;base64,{b64}) format('woff2')}}"


FACES = {"audiowide": "QA", "spacegrotesk-500": "QS5", "spacegrotesk-600": "QS6", "inter-400": "QI4",
         "inter-500": "QI5", "jetbrainsmono-500": "QM5", "jetbrainsmono-700": "QM7"}


def fonts(*names: str) -> str:
    return "".join(face(n, FACES[n]) for n in names)


def width(text: str, font: str, size: float, tracking: float = 0.0) -> float:
    m = METRICS[font]
    adv = sum(m["adv"].get(ch, m["adv"]["n"]) for ch in text) * size / m["upm"]
    return adv + tracking * max(len(text) - 1, 0)


def wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if width(trial, font, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def e(s: str) -> str:
    return escape(s, {'"': "&quot;"})


def svg(w: int, h: int, title: str, css: str, body: str, defs: str = "") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{e(title)}"><title>{e(title)}</title><defs><style>{css}</style>{defs}</defs>{body}</svg>\n')


GLOW = ('<filter id="glow" x="-30%" y="-80%" width="160%" height="260%"><feGaussianBlur stdDeviation="7"/></filter>'
        '<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3"/></filter>')
MOTION = """@media (prefers-reduced-motion: no-preference) {
 .pulse { transform-box: fill-box; transform-origin: center; animation: pulse 2.4s ease-out infinite; }
 @keyframes pulse { 0% { transform: scale(1); opacity: .55 } 100% { transform: scale(3.2); opacity: 0 } }
 .breathe { animation: breathe 4.8s ease-in-out infinite; }
 @keyframes breathe { 0%,100% { opacity: .55 } 50% { opacity: 1 } }
}"""


def status_dot(x: float, y: float) -> str:
    return (f'<circle class="pulse" cx="{x}" cy="{y}" r="5" fill="{ORANGE}"/>'
            f'<circle cx="{x}" cy="{y}" r="5" fill="{ORANGE}"/>')


def logo_icon(x: float, y: float, size: float) -> str:
    s = size / 64
    return (f'<g transform="translate({x} {y}) scale({s:.4f})"><rect width="64" height="64" rx="14" fill="{ORANGE}"/>'
            f'<g transform="translate(12.61 12.00) scale(0.04211)" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="40" '
            f'stroke-linejoin="round">{MARK}</g></g>')


# ---------------------------------------------------------------------------------------------- header
def header() -> str:
    W, H, cx, cy = 1280, 460, 1012, 232
    eyebrow = "FOUNDER  ·  QUARKTEX"
    l1, l2a, l2b = "I build the infrastructure where", "AI agents work ", "together"
    x2b = 72 + width(l2a, "spacegrotesk-500", 38)
    orbits = [(76, 24, "", [(30, 5, "#FFFFFF"), (210, 4, "#FFFFFF")]),
              (128, 36, " reverse", [(80, 6, ORANGE), (200, 4, "#FFFFFF"), (310, 5, "#FFFFFF")]),
              (182, 52, "", [(0, 7, "#FFFFFF"), (125, 5, ORANGE), (245, 4, "#FFFFFF")])]
    rings, planets = [], []
    import math
    for i, (r, dur, rev, ps) in enumerate(orbits):
        rings.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#FFFFFF" stroke-opacity=".09"/>')
        dots = "".join(f'<circle cx="{cx + r * math.cos(math.radians(a)):.1f}" cy="{cy + r * math.sin(math.radians(a)):.1f}" '
                       f'r="{s}" fill="{c}"{" filter=" + chr(34) + "url(#soft)" + chr(34) if c == ORANGE else ""}/>'
                       f'<circle cx="{cx + r * math.cos(math.radians(a)):.1f}" cy="{cy + r * math.sin(math.radians(a)):.1f}" '
                       f'r="{s * .7:.1f}" fill="{c}"/>' for a, s, c in ps)
        planets.append(f'<g class="orb" style="animation-duration:{dur}s;animation-direction:{"reverse" if rev else "normal"}">{dots}</g>')
    css = fonts("audiowide", "spacegrotesk-500", "spacegrotesk-600", "inter-400", "inter-500") + f"""
.eb {{ font: 600 13px QS6; letter-spacing: 3.2px; fill: {MUTED_D} }}
.name {{ font: 400 76px QA; fill: {TXT_D} }}
.h {{ font: 500 38px QS5; fill: #ECEAE7 }}
.acc {{ fill: {ORANGE} }}
.sub {{ font: 400 19px QI4; fill: #A8A6A3 }}
.subb {{ font: 500 19px QI5; fill: {TXT_D} }}
{MOTION}
@media (prefers-reduced-motion: no-preference) {{
 .orb {{ transform-box: view-box; transform-origin: {cx}px {cy}px; animation: spin linear infinite; }}
 @keyframes spin {{ to {{ transform: rotate(360deg) }} }}
 .core {{ transform-box: fill-box; transform-origin: center; animation: corepulse 3.6s ease-out infinite; }}
 @keyframes corepulse {{ 0% {{ transform: scale(1); opacity: .5 }} 100% {{ transform: scale(2.6); opacity: 0 }} }}
}}"""
    defs = GLOW + (f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{INK0}"/>'
                   f'<stop offset="1" stop-color="#19191B"/></linearGradient>'
                   f'<radialGradient id="halo" cx="{cx}" cy="{cy}" r="330" gradientUnits="userSpaceOnUse">'
                   f'<stop offset="0" stop-color="{ORANGE}" stop-opacity=".42"/><stop offset=".55" stop-color="{ORANGE}" stop-opacity=".08"/>'
                   f'<stop offset="1" stop-color="{ORANGE}" stop-opacity="0"/></radialGradient>'
                   f'<pattern id="dots" width="28" height="28" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="#FFFFFF" fill-opacity=".05"/></pattern>'
                   f'<clipPath id="c"><rect width="{W}" height="{H}" rx="24"/></clipPath>')
    body = f"""<g clip-path="url(#c)">
<rect width="{W}" height="{H}" fill="url(#bg)"/><rect width="{W}" height="{H}" fill="url(#dots)"/>
<rect class="breathe" width="{W}" height="{H}" fill="url(#halo)"/>
{''.join(rings)}{''.join(planets)}
<circle class="core" cx="{cx}" cy="{cy}" r="34" fill="none" stroke="{ORANGE}" stroke-width="2"/>
<circle cx="{cx}" cy="{cy}" r="40" fill="{ORANGE}" opacity=".35" filter="url(#glow)"/>
{logo_icon(cx - 30, cy - 30, 60)}
{status_dot(79, 95)}
<text x="98" y="100" class="eb">{e(eyebrow)}</text>
<text x="70" y="190" class="name">Prasanna K</text>
<text x="72" y="262" class="h">{e(l1)}</text>
<text x="72" y="310" class="h">{e(l2a)}</text>
<text x="{x2b:.1f}" y="310" class="h acc breathe" filter="url(#glow)">{e(l2b)}</text>
<text x="{x2b:.1f}" y="310" class="h acc">{e(l2b)}<tspan class="h">.</tspan></text>
<text x="72" y="372" class="sub">QuarkTex: your AI, and a Hive of agents behind it.</text>
<text x="72" y="402" class="sub">Backed by <tspan class="subb">ISB</tspan>. Supported by <tspan class="subb">Google Cloud</tspan>.</text>
</g>"""
    return svg(W, H, "Prasanna K. Founder, QuarkTex. I build the infrastructure where AI agents work together.", css, body, defs)


# ---------------------------------------------------------------------------------------------- stats
def stats(data: dict, today: dt.date) -> str:
    W, H = 1280, 432
    ly = data["last_year"]
    total_ly = ly["totalContributions"]
    alltime = sum(data["year_totals"].values())
    cur, longest = streaks(data["days"], today)
    ly_days = [day for w in ly["weeks"] for day in w["contributionDays"]]
    active = sum(1 for day in ly_days if day["contributionCount"] > 0)
    since = dt.datetime.fromisoformat(data["created"].replace("Z", "+00:00")).strftime("%b %Y")
    weeks = [(w["contributionDays"][0]["date"], sum(x["contributionCount"] for x in w["contributionDays"])) for w in ly["weeks"]]
    weeks = weeks[-52:]
    peak = max(v for _, v in weeks) or 1
    x0, x1, base, hmax = 652, 1208, 236, 150
    slot = (x1 - x0) / len(weeks)
    bw = slot * .64
    bars, labels, seen = [], [], set()
    for i, (d0, v) in enumerate(weeks):
        h = max(2.0, hmax * (v / peak) ** .5) if v else 2.0     # square-root scale: quiet weeks stay visible
        x = x0 + i * slot + (slot - bw) / 2
        recent = i >= len(weeks) - 8
        bars.append(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="{min(bw / 2, 3):.1f}" '
                    f'fill="{ORANGE if recent else TXT_L}" fill-opacity="{1 if recent else .82}"/>')
        mon = dt.date.fromisoformat(d0).strftime("%b")
        if mon not in seen and dt.date.fromisoformat(d0).day <= 7:
            seen.add(mon)
            labels.append(f'<text x="{x:.1f}" y="{base + 22}" class="ax">{mon}</text>')
    glow_bars = "".join(b for b in bars[-8:])
    num = f"{total_ly:,}"
    nw = width(num, "jetbrainsmono-700", 112)
    cols = [(f"{alltime:,}", f"contributions since {since}"), (f"{cur} days", "current streak"),
            (f"{longest} days", "longest streak"), (f"{active}", "active days in 12 months")]
    metrics = "".join(f'<text x="{72 + i * 290}" y="350" class="m">{e(a)}</text>'
                      f'<text x="{72 + i * 290}" y="377" class="ml">{e(b)}</text>' for i, (a, b) in enumerate(cols))
    css = fonts("spacegrotesk-600", "inter-400", "inter-500", "jetbrainsmono-500", "jetbrainsmono-700") + f"""
.eb {{ font: 600 12.5px QS6; letter-spacing: 3px; fill: {MUTED_L} }}
.big {{ font: 700 112px QM7; fill: {TXT_L}; letter-spacing: -3px }}
.lab {{ font: 500 20px QI5; fill: {BODY_L} }}
.m {{ font: 700 34px QM7; fill: {TXT_L}; letter-spacing: -.5px }}
.ml {{ font: 400 15px QI4; fill: {MUTED_L} }}
.ax {{ font: 500 11.5px QM5; fill: #9A9A9A }}
.cap {{ font: 500 12px QM5; fill: #9A9A9A }}
{MOTION}"""
    defs = GLOW + (f'<radialGradient id="h" cx="{72 + nw / 2:.0f}" cy="158" r="{nw * .62:.0f}" gradientUnits="userSpaceOnUse">'
                   f'<stop offset="0" stop-color="{ORANGE}" stop-opacity=".30"/><stop offset="1" stop-color="{ORANGE}" stop-opacity="0"/></radialGradient>'
                   f'<clipPath id="c"><rect width="{W}" height="{H}" rx="24"/></clipPath>')
    body = f"""<g clip-path="url(#c)">
<rect width="{W}" height="{H}" fill="{OFF}"/>
<ellipse class="breathe" cx="{72 + nw / 2:.0f}" cy="158" rx="{nw * .62:.0f}" ry="96" fill="url(#h)"/>
{status_dot(79, 73)}
<text x="96" y="78" class="eb">PROOF OF WORK  ·  LIVE FROM GITHUB</text>
<text x="{x1}" y="78" text-anchor="end" class="cap">weekly contributions, last 52 weeks, square-root scale</text>
<text x="64" y="196" class="big">{num}</text>
<text x="72" y="236" class="lab">contributions on GitHub in the last 12 months</text>
<g class="breathe" filter="url(#soft)">{glow_bars}</g>
{''.join(bars)}{''.join(labels)}
<path d="M72 290 H{x1}" stroke="{BORDER_L}"/>
{metrics}
<text x="{x1}" y="412" text-anchor="end" class="cap">updated {today.strftime("%-d %b %Y")}  ·  GitHub GraphQL API, private work shown as counts</text>
</g>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="24" fill="none" stroke="{BORDER_L}"/>"""
    title = f"{num} contributions on GitHub in the last 12 months; {alltime:,} since {since}; current streak {cur} days; longest {longest} days."
    return svg(W, H, title, css, body, defs)


# ---------------------------------------------------------------------------------------------- cards
def card(w: int, h: int, eyebrow: str, title: str, desc: str, proof: str, wide: bool = False, art: str = "") -> str:
    tx = 40
    title_font, title_size = ("audiowide", 40) if wide else ("spacegrotesk-600", 32)
    desc_w = (w - 420) if wide else (w - 96)
    lines = wrap(desc, "inter-400", 17, desc_w)[:3]
    ty = 116 if not wide else 124
    title_x = tx + (72 if wide else 0)
    desc_svg = "".join(f'<text x="{tx}" y="{ty + 44 + i * 26}" class="d">{e(l)}</text>' for i, l in enumerate(lines))
    proof_y = h - 34
    arrow = (f'<g transform="translate({w - 52} 34)" fill="none" stroke="{MUTED_D}" stroke-width="2" stroke-linecap="round" '
             f'stroke-linejoin="round"><path d="M2 14 L14 2 M5 2 H14 V11"/></g>')
    css = fonts(title_font, "spacegrotesk-600", "inter-400", "jetbrainsmono-500") + f"""
.eb {{ font: 600 12px QS6; letter-spacing: 2.8px; fill: {MUTED_D} }}
.t {{ font: {"400" if wide else "600"} {title_size}px {"QA" if wide else "QS6"}; fill: {TXT_D} }}
.d {{ font: 400 17px QI4; fill: #B4B1AD }}
.p {{ font: 500 13.5px QM5; fill: {BODY_D} }}
{MOTION}"""
    defs = GLOW + (f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{INK1}"/>'
                   f'<stop offset="1" stop-color="#1D1D1F"/></linearGradient><clipPath id="c"><rect width="{w}" height="{h}" rx="20"/></clipPath>')
    icon = logo_icon(tx, ty - 48, 56) if wide else ""
    body = f"""<g clip-path="url(#c)"><rect width="{w}" height="{h}" fill="url(#bg)"/>{art}
{status_dot(tx + 6, 45)}<text x="{tx + 22}" y="50" class="eb">{e(eyebrow)}</text>{arrow}
{icon}<text x="{title_x}" y="{ty}" class="t">{e(title)}</text>{desc_svg}
<circle cx="{tx + 4}" cy="{proof_y - 5}" r="3" fill="{ORANGE}"/><text x="{tx + 16}" y="{proof_y}" class="p">{e(proof)}</text></g>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20" fill="none" stroke="#FFFFFF" stroke-opacity=".09"/>"""
    return svg(w, h, f"{title}. {desc}", css, body, defs)


def hive(cx: float, cy: float, r: float) -> str:
    import math
    cells = [(0, 0)] + [(math.cos(math.radians(30 + 60 * k)) * r * 1.74, math.sin(math.radians(30 + 60 * k)) * r * 1.74) for k in range(6)]
    out = []
    for i, (dx, dy) in enumerate(cells):
        pts = " ".join(f"{cx + dx + r * math.cos(math.radians(60 * k)):.1f},{cy + dy + r * math.sin(math.radians(60 * k)):.1f}" for k in range(6))
        if i == 0:
            out.append(f'<polygon points="{pts}" fill="{ORANGE}" opacity=".9" filter="url(#glow)"/>'
                       f'<polygon points="{pts}" fill="{ORANGE}"/>')
        else:
            out.append(f'<polygon points="{pts}" fill="#FFFFFF" fill-opacity=".03" stroke="#FFFFFF" stroke-opacity=".16"/>'
                       f'<circle cx="{cx + dx:.1f}" cy="{cy + dy:.1f}" r="4" fill="#FFFFFF" class="hv" style="animation-delay:{i * .5:.1f}s"/>')
    style = ('<style>@media (prefers-reduced-motion: no-preference) { .hv { animation: hv 3s ease-in-out infinite; } '
             f'@keyframes hv {{ 0%,100% {{ fill: #FFFFFF; opacity: .35 }} 50% {{ fill: {ORANGE}; opacity: 1 }} }} }}</style>')
    mark = (f'<g transform="translate({cx - 17} {cy - 17}) scale(0.0366)" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="40" '
            f'stroke-linejoin="round">{MARK}</g>')
    return style + "".join(out) + mark


def cards(data: dict) -> dict[str, str]:
    r = data["repos"]
    stars = lambda n: f"{n} star" + ("" if n == 1 else "s")  # noqa: E731
    return {
        "quarktex": card(1280, 260, "THE COMPANY  ·  LIVE", "QuarkTex",
                         "Your AI, and a Hive of agents behind it. One ask: the right agent takes the lead, others join in "
                         "when the task needs them, and you get one finished result.",
                         "Backed by ISB  ·  Supported by Google Cloud  ·  quarktex.com", wide=True,
                         art=hive(1080, 130, 37)),
        "qcobrain": card(624, 250, "OPEN SOURCE  ·  MIT", "QcoBrain",
                         "Provenance-governed memory for AI agents. A self-evolving second brain where every write cites "
                         "a source, or it is refused.",
                         f"{stars(r['qcobrain']['stars'])}  ·  Python  ·  Markdown + grep"),
        "wishlabs": card(624, 250, "OPEN SOURCE  ·  MIT", "Wish Labs",
                         "Describe a gadget in plain words. Get the 3D-printed shell, the circuit board, the firmware and "
                         "a delivered price.",
                         f"{r['wishlabs']['commits']:,} commits  ·  CadQuery, KiCad, Gemini"),
        "plugbook": card(624, 250, "LIVE  ·  PAID PLANS", "Plugbook",
                         "An AI video editor. Bring your footage, say what you are making, and it cuts, captions, "
                         "reframes and finishes the video.",
                         "plugbook.si  ·  Free, Pro and Max plans"),
        "ivi": card(624, 250, "OPEN SOURCE  ·  MIT", "IVI Forum",
                    "Member directory and forum for I-Venture @ ISB founders, with LinkedIn sign-in, a cohort "
                    "directory and threaded discussions.",
                    f"{stars(r['ivi']['stars'])}  ·  Next.js 16  ·  Firestore  ·  Cloud Run"),
    }


def main() -> None:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    data = fetch()
    (ASSETS / "cards").mkdir(parents=True, exist_ok=True)
    (ASSETS / "header.svg").write_text(header())
    (ASSETS / "stats.svg").write_text(stats(data, today))
    for k, v in cards(data).items():
        (ASSETS / "cards" / f"{k}.svg").write_text(v)
    cur, longest = streaks(data["days"], today)
    print(json.dumps({"last_year": data["last_year"]["totalContributions"], "all_time": sum(data["year_totals"].values()),
                      "years": data["year_totals"], "current_streak": cur, "longest_streak": longest,
                      "repos": data["repos"]}))


if __name__ == "__main__":
    main()
