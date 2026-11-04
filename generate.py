#!/usr/bin/env python3
"""Live fire-watchtower banner above a sea of treetops.
Season follows the date, light follows the real sun position in Zurich."""
import json
import math
import os
import random
import sys

try:  # realistic raster layers (numpy + Pillow); flat vector art otherwise
    import numpy as np
    import terrain as TR
except Exception:  # pragma: no cover
    np = TR = None
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:  # running inside the browser playground
    _HERE = "."
TERRAIN_DIR = os.environ.get("LOOKOUT_TERRAIN", os.path.join(_HERE, "assets", "terrain"))
from datetime import datetime, timezone

LAT, LON = 47.3769, 8.5417  # Zurich
W, H = 1200, 320


# ---------- sun ----------
def sun_position(now_utc, lat=None, lon=None):
    lat = LAT if lat is None else lat
    lon = LON if lon is None else lon
    doy = now_utc.timetuple().tm_yday
    hour = now_utc.hour + now_utc.minute / 60
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    ha = (hour * 60 + eqt + 4 * lon) / 4 - 180
    lat = math.radians(lat)
    cz = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(math.radians(ha))
    return 90 - math.degrees(math.acos(max(-1, min(1, cz)))), ha


def season_of(dt):
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(dt.month, "autumn")


# random weather, changes every 3 hours, weighted by season
WEATHER_ODDS = {
    "spring": {"clear": 35, "cloudy": 30, "rain": 25, "storm": 10},
    "summer": {"clear": 45, "cloudy": 25, "rain": 10, "storm": 20},
    "autumn": {"clear": 25, "cloudy": 30, "rain": 20, "fog": 25},
    "winter": {"clear": 30, "cloudy": 20, "snow": 35, "fog": 15},
}
OVERCAST = {"clear": 0, "cloudy": .4, "rain": .62, "storm": .8, "fog": .5, "snow": .68}
SEASON_NAME = {"spring": "spring", "summer": "summer", "autumn": "autumn", "winter": "winter"}
# older configs used German weather names
LEGACY_WEATHER = {"klar": "clear", "wolkig": "cloudy", "regen": "rain", "gewitter": "storm", "nebel": "fog", "schnee": "snow"}


def weather_of(dt, season):
    r = random.Random(f"{dt:%Y-%m-%d}-{dt.hour // 3}")
    odds = WEATHER_ODDS[season]
    return r.choices(list(odds), weights=list(odds.values()))[0]


# ---------- color ----------
def rgb(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(rgb(a), rgb(b)))


NIGHT = dict(top="#050918", mid="#0e1735", bot="#253157", haze="#36426b", mtn="#29345e",
             msnow="#8592c0", tint="#141d44", k=0.6)
DUSK = dict(top="#222c5a", mid="#68598c", bot="#f19d76", haze="#c296a0", mtn="#69669a",
            msnow="#f4d5cf", tint="#f09a72", k=0.14)
DAY = dict(top="#3a89d4", mid="#7ab5e8", bot="#dbeeff", haze="#c6dcf1", mtn="#8fb0d3",
           msnow="#ffffff", tint="#ffffff", k=0.0)

SEASON = {
    "spring": dict(con=["#3c6f47", "#467b4e", "#335f3f"], acc=["#86c35d", "#a4d36d", "#6fae4f"], acc_frac=.32,
                   round=True, cap=40, snowtips=False, bloom=["#f7c3d4", "#ffffff", "#f3a9c2"],
                   haze_shift="#e8f3e0"),
    "summer": dict(con=["#1f4d37", "#245740", "#1a4230"], acc=["#3b7a3a", "#4a8a3e", "#32702f"], acc_frac=.3,
                   round=True, cap=16, snowtips=False, bloom=None, haze_shift="#f3ecd4"),
    "autumn": dict(con=["#2a4a3a", "#2f5240", "#243f33"], acc=["#e0892b", "#cf5a2e", "#e8b440", "#b8412c", "#d97a2a"],
                   acc_frac=.36, round=True, cap=30, snowtips=False, bloom=None, haze_shift="#f1d8c0"),
    "winter": dict(con=["#193731", "#1e3f38", "#15302b"], acc=[], acc_frac=0, round=False, cap=70,
                   snowtips=True, bloom=None, haze_shift="#e6edf7"),
}


def sky(elev):
    if elev <= -9:
        return dict(NIGHT)
    if elev >= 12:
        return dict(DAY)
    a, b, t = (NIGHT, DUSK, (elev + 9) / 9) if elev < 0 else (DUSK, DAY, elev / 12)
    return {k: (mix(a[k], b[k], t) if isinstance(a[k], str) else a[k] + (b[k] - a[k]) * t) for k in a}


def poly(pts):
    return "M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in pts) + "Z"


# ---------- trees (tops only) ----------
def conifer(rnd, x, base, h, wf):
    w = h * wf * rnd.uniform(0.85, 1.15)
    apex = (x + rnd.uniform(-0.8, 0.8), base - h)
    sides, snow = [], []
    for s in (-1, 1):
        pts, prev = [], apex
        for i in range(4):
            t = (i + 1) / 4
            yb = base - h + h * t
            ww = w * t ** 0.85 * rnd.uniform(0.85, 1.12)
            tip = (x + s * ww, yb + rnd.uniform(-1, 1))
            notch = (x + s * ww * 0.48, yb - h * 0.035)
            ax, ay = prev
            bx, by = tip
            snow.append([(ax, ay), (bx, by - .4), (ax + (bx - ax) * .55, ay + (by - ay) * .55 + max(2.4, h * .08))])
            pts += [tip, notch]
            prev = notch
        pts.append((x + s * w * 1.02, H + 10))
        sides.append(pts)
    return [*sides[0][::-1], apex, *sides[1]], snow, sides, apex


def circ(cx, cy, r):
    return f"M{cx - r:.1f} {cy:.1f}a{r:.1f} {r:.1f} 0 1 0 {2 * r:.1f} 0a{r:.1f} {r:.1f} 0 1 0 {-2 * r:.1f} 0"


def crown(rnd, x, base, h, light):
    """Leafy dome: dark full silhouette, mid-tone lumps, sun-side highlights."""
    R = h * 0.32
    lumps = []
    n = 7
    for j in range(n):
        t = j / (n - 1)
        lumps.append((x + (t - .5) * 2 * R * .9 + rnd.uniform(-2, 2),
                      base - h * .42 - math.sin(math.pi * t) * h * .22 + rnd.uniform(-2, 2),
                      R * (.42 + .26 * math.sin(math.pi * t)) * rnd.uniform(.85, 1.15)))
    for dx in (-.32, .3):
        lumps.append((x + dx * R + rnd.uniform(-2, 2), base - h * .74 + rnd.uniform(-2, 2), R * rnd.uniform(.4, .5)))
    body = poly([(x - R * 1.0, base - h * .42), (x + R * 1.0, base - h * .42), (x + R * 1.55, H + 10), (x - R * 1.55, H + 10)])
    dark = "".join(circ(*l) for l in lumps) + body
    mid = "".join(circ(cx + light * r * .12, cy - r * .16, r * .82) for cx, cy, r in lumps) + \
        poly([(x - R * .9, base - h * .42), (x + R * .9, base - h * .42), (x + R * 1.3, base - h * .1), (x - R * 1.3, base - h * .1)])
    hi = "".join(circ(cx + light * r * .28, cy - r * .32, r * .5) for cx, cy, r in lumps
                 if (cx - x) * light > -R * .25 and cy < base - h * .5)
    return dark, mid, hi


def canopy(rnd, base, hmin, hmax, wf, spacing, k, S, haze, T, bloom_n=0, light=-1, lk=.2, sway=False, spawn=None):
    groups, snow, blooms, trees = {}, [], [], []
    xs = [i * spacing + rnd.uniform(-spacing * .35, spacing * .35) for i in range(-1, int(W / spacing) + 2)]
    for x in xs:
        b = base + rnd.uniform(-4, 4) + 3 * math.sin(x / 90)
        h = rnd.uniform(hmin, hmax)
        layers = []  # (color, d)
        accent = S["acc"] and rnd.random() < S["acc_frac"]
        col = rnd.choice(S["acc"]) if accent else rnd.choice(S["con"])
        if accent and S["round"] and rnd.random() < 0.38:
            dk, md, hi = crown(rnd, x, b, h * 0.9, light)
            layers += [(mix(col, "#0b1610", .3), dk), (col, md)]
            if hi:
                layers.append((mix(col, "#fff1c4", lk * 1.4), hi))
        else:
            pts, sn, sides, apex = conifer(rnd, x, b, h, wf)
            li = 0 if light < 0 else 1
            layers += [(mix(col, "#0b1610", .12), poly(pts)),
                       (mix(col, "#fff1c4", lk), poly([apex] + sides[li] + [(x, H + 10)]))]
            if S["snowtips"]:
                layers.append(("#f4f7fc", "".join(poly(q) for q in sn)))
        if accent and spawn is not None:
            spawn.append((x, b - h * .6))
        if sway:
            trees.append((x, b, layers))
        else:
            for c, d in layers:
                groups.setdefault(c, []).append(d)
    if S["bloom"] and bloom_n:
        for _ in range(bloom_n):
            blooms.append((rnd.uniform(0, W), base - rnd.uniform(-6, hmax * .5), rnd.choice(S["bloom"])))
    fill = lambda c: T(mix(c, haze, k * (.8 if c == "#f4f7fc" else 1)), .8 if c == "#f4f7fc" else 1)
    out = "".join(f'<path d="{"".join(ds)}" fill="{fill(c)}"/>' for c, ds in groups.items())
    for x, b, layers in trees:
        out += (f'<g class="sw" style="transform-origin:{x:.0f}px {b + 40:.0f}px;animation-duration:{rnd.uniform(2.6, 4.2):.1f}s;'
                f'animation-delay:-{rnd.uniform(0, 4):.1f}s">' + "".join(f'<path d="{d}" fill="{fill(c)}"/>' for c, d in layers) + '</g>')
    for x, y, c in blooms:
        out += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rnd.uniform(1.2, 2.4):.1f}" fill="{T(mix(c, haze, k))}"/>'
    return out


# ---------- realistic raster layers ----------
FIRS = {
    "spring": ["#2a5236", "#30603d", "#264a31"],
    "summer": ["#1f4a33", "#24563a", "#1b4130"],
    "autumn": ["#24442f", "#2b4b34", "#203b2b"],
    "winter": ["#1f3a33", "#25423a", "#1b332d"],
}


def _lerp3(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, t))


def raster_scene(p, haze_hex, elev, nf, ov, season, weather, wind, sun_x, now_utc):
    rgb = TR.hexrgb
    if elev <= -9:
        light = rgb("#6f82b8") * .2
    elif elev < 0:
        light = _lerp3(rgb("#6f82b8") * .2, rgb("#ff9e6a") * .85, (elev + 9) / 9)
    elif elev < 12:
        light = _lerp3(rgb("#ff9e6a") * .85, rgb("#fff2df") * 1.15, elev / 12)
    else:
        light = rgb("#fff2df") * 1.15
    light = light * (1 - ov * (.86 if weather == "storm" else .78))
    amb = rgb(p["mid"]) * .55 + rgb(p["top"]) * .22 + rgb(p["bot"]) * .12
    haze = rgb(haze_hex)
    fog_k = {"clear": 1 / 21000, "cloudy": 1 / 16000, "rain": 1 / 9000, "storm": 1 / 8500, "snow": 1 / 7500, "fog": 1 / 4200}[weather]
    morning = 1.0 if -3 < elev < 9 else 0.0
    valley = {"fog": .9, "rain": .45, "storm": .4, "snow": .35}.get(weather, .12 + .35 * morning)
    snow_boost = {"snow": 700}.get(weather, 0)

    G = TR.gbuffer(TERRAIN_DIR)
    terr = TR.shade_terrain(G, season, dict(elev=elev, x=sun_x), light, haze, amb, fog_k, snow_boost, valley)
    out = {"defs": "", "spawn": []}
    out["terrain"] = f'<image x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="none" href="{TR.to_webp_uri(terr, 82)}"/>'

    # clouds: tileable bands drifting with the wind
    cov = {"clear": .16, "cloudy": .5, "rain": .84, "storm": .9, "fog": .55, "snow": .62}[weather]
    lit = np.clip(_lerp3(rgb("#ffffff") * (.3 + .7 * min(1.2, float(light.mean()) * 1.1)) + amb * .25, rgb(p["bot"]), .25), 0, 1)
    dark = np.clip(_lerp3(rgb("#5c6470"), rgb(p["mid"]), .55) * (1 - .35 * ov), 0, 1)
    if weather == "storm":
        lit, dark = lit * .62, dark * .55
    layers = [("ca", 190, cov * .85, 1.0 if cov > .3 else .7, 420 / (1 + wind), 3)]
    if cov > .45:
        layers.append(("cb", 150, min(.95, cov + .05), 1.0, 170 / (1 + wind), 9))
    cl, low = "", ""
    for cid, ch, c, al, dur, seed in layers:
        arr = TR.cloud_layer(W, ch, c, sun_x, lit, dark * (.85 if cid == "cb" else 1), al, seed=seed)
        out["defs"] += f'<image id="{cid}" width="{W}" height="{ch}" preserveAspectRatio="none" href="{TR.to_webp_uri(arr, 72)}"/>'
        tile = f'<g class="ck" style="animation-duration:{dur:.0f}s"><use href="#{cid}"/><use href="#{cid}" x="{W}"/></g>'
        if cid == "cb":  # low cloud deck hangs in front of the peaks
            low += f'<g transform="translate(0 {12 if weather == "storm" else 22})">{tile}</g>'
        else:
            cl += tile
    # moving fog wisps over the valley
    famt = {"fog": 1.0, "rain": .55, "storm": .45, "snow": .45}.get(weather, .2 + .45 * morning)
    farr = TR.fog_layer(W, 120, famt, np.clip(haze * 1.04, 0, 1))
    out["defs"] += f'<image id="fw" width="{W}" height="120" preserveAspectRatio="none" href="{TR.to_webp_uri(farr, 70)}"/>'
    fog = f'<g class="ck" style="animation-duration:{260 / (1 + wind):.0f}s"><use href="#fw" y="150"/><use href="#fw" x="{W}" y="150"/></g>'
    out["clouds"] = cl
    out["low"] = low
    # grain + vignette
    out["defs"] += ('<filter id="gr" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".85" '
                    'numOctaves="2" seed="4" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 .5 0 0 0 0 .5 0 0 0 0 .5 0 0 0 1.6 -.5"/></filter>'
                    '<radialGradient id="vg" cx="50%" cy="45%" r="75%"><stop offset=".55" stop-color="#000" stop-opacity="0"/>'
                    '<stop offset="1" stop-color="#000" stop-opacity=".38"/></radialGradient>')

    # firs: a hazy band behind the tower and a crisp band in front of it
    rng = np.random.default_rng(2009)
    cols = FIRS[season]
    snow = season == "winter" or weather == "snow"
    autumn = season == "autumn"
    mid = TR.fir_band(W, H, 312, 30, 80, 170, cols, light * .9 + amb * .3, sun_x, haze, .22, snow, autumn, rng, scale=.7)
    spawn = []
    front = TR.fir_band(W, H, 342, 85, 180, 46, cols, light * .9 + amb * .3, sun_x, haze, .06, snow, autumn, rng, spawn=spawn)
    out["mid"] = fog + f'<image width="{W}" height="{H}" href="{TR.to_webp_uri(mid, 80)}"/>'
    out["front"] = f'<image width="{W}" height="{H}" href="{TR.to_webp_uri(front, 82)}"/>'
    out["spawn"] = [(x, y) for x, y in spawn if 0 < x < W and y > 150]
    return out


# ---------- scene ----------
def build(now_utc, season=None, weather=None, name="FLACO2009", lat=None, lon=None, xmas=None, realistic=None):
    elev, ha = sun_position(now_utc, lat, lon)
    xmas = now_utc.month == 12 if xmas is None else xmas
    name = "".join(c for c in str(name).upper() if c.isalnum() or c in " -_.")[:24] or "LOOKOUT"
    season = season or season_of(now_utc)
    weather = weather or weather_of(now_utc, season)
    ov = OVERCAST[weather]
    wind = {"clear": .2, "cloudy": .5, "rain": .9, "storm": 1.6, "fog": 0, "snow": .4}[weather]
    S = SEASON[season]
    p = sky(elev)
    if ov:
        _nf = max(0.0, min(1.0, (3 - elev) / 11))
        grey = mix("#6c7480" if weather == "storm" else "#97a0ab" if weather == "rain" else "#a3abb5", "#151820", _nf)
        for k in ("top", "mid", "bot", "haze", "mtn"):
            p[k] = mix(p[k], grey, ov * (1.1 if k == "top" else .85))
        if _nf < .6:
            p["tint"], p["k"] = mix(p["tint"], "#3b4352", ov), max(p["k"], ov * .32)
    haze = mix(p["haze"], S["haze_shift"], 0.25 * (1 - min(1, max(0, (2 - elev) / 10))))
    nf = max(0.0, min(1.0, (3 - elev) / 11))           # 0 day .. 1 dark
    T = lambda c, k=1.0: mix(c, p["tint"], p["k"] * k)  # scene lighting
    rnd = random.Random(2009)
    R = (TR is not None and os.path.exists(os.path.join(TERRAIN_DIR, "depth.png"))) if realistic is None else realistic
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">']
    o.append(f'''<defs>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{p["top"]}"/><stop offset=".62" stop-color="{p["mid"]}"/><stop offset="1" stop-color="{p["bot"]}"/></linearGradient>
<linearGradient id="fog" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{haze}" stop-opacity="0"/><stop offset=".7" stop-color="{haze}" stop-opacity=".6"/><stop offset="1" stop-color="{haze}" stop-opacity="0"/></linearGradient>
<radialGradient id="halo"><stop offset="0" stop-color="#fff4c4" stop-opacity=".85"/><stop offset=".35" stop-color="#fff4c4" stop-opacity=".22"/><stop offset="1" stop-color="#fff4c4" stop-opacity="0"/></radialGradient>
<radialGradient id="bolt"><stop offset="0" stop-color="#e6edff" stop-opacity=".8"/><stop offset="1" stop-color="#e6edff" stop-opacity="0"/></radialGradient>
<linearGradient id="met" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff"/></linearGradient>
<radialGradient id="warm"><stop offset="0" stop-color="#ffc36a" stop-opacity=".75"/><stop offset="1" stop-color="#ffc36a" stop-opacity="0"/></radialGradient>
<mask id="cres"><rect width="{W}" height="{H}" fill="#fff"/><circle id="mc" cx="0" cy="0" r="0" fill="#000"/></mask>
<clipPath id="c"><rect width="{W}" height="{H}" rx="14"/></clipPath>
</defs>
<style>
.fa{{animation:fa linear infinite}}@keyframes fa{{from{{transform:translateY(-14px)}}to{{transform:translateY({H + 16}px)}}}}
.sa{{animation:sa ease-in-out infinite alternate}}@keyframes sa{{from{{transform:translateX(-10px)}}to{{transform:translateX(10px)}}}}
.sb{{animation:sb ease-in-out infinite alternate}}@keyframes sb{{from{{transform:translateX(-26px)}}to{{transform:translateX(18px)}}}}
.sp{{transform-box:fill-box;transform-origin:center;animation:sp linear infinite}}@keyframes sp{{from{{transform:rotate(0)}}to{{transform:rotate(360deg)}}}}
.tw{{animation:tw 2.8s ease-in-out infinite alternate}}@keyframes tw{{from{{opacity:.15}}to{{opacity:1}}}}
.ff{{animation:ff ease-in-out infinite alternate}}@keyframes ff{{0%{{opacity:0;transform:translate(0,0)}}50%{{opacity:1}}100%{{opacity:.1;transform:translate(14px,-10px)}}}}
.fl{{transform-box:fill-box;transform-origin:left center;animation:fl 1.6s ease-in-out infinite alternate}}@keyframes fl{{from{{transform:skewY(-6deg) scaleX(.92)}}to{{transform:skewY(5deg) scaleX(1)}}}}
.bd{{animation:bd linear infinite}}@keyframes bd{{from{{transform:translateX(-120px)}}to{{transform:translateX({W + 120}px)}}}}
.wg{{transform-box:fill-box;transform-origin:center;animation:wg .45s ease-in-out infinite alternate}}@keyframes wg{{from{{transform:scaleY(1)}}to{{transform:scaleY(-.5)}}}}
.dk{{animation:dk linear infinite}}@keyframes dk{{from{{transform:translateX(0)}}to{{transform:translateX(-{W}px)}}}}
.ck{{animation:ck linear infinite}}@keyframes ck{{from{{transform:translateX(0)}}to{{transform:translateX(-{W}px)}}}}
.cd{{animation:cd linear infinite}}@keyframes cd{{from{{transform:translateX(-360px)}}to{{transform:translateX({W + 360}px)}}}}
.rn{{animation:rn linear infinite}}@keyframes rn{{from{{transform:translate(0,-30px)}}to{{transform:translate(-40px,{H + 30}px)}}}}
.lt{{opacity:0;animation:lt 7s linear infinite}}@keyframes lt{{0%,90%,91.6%,92.4%,95%,100%{{opacity:0}}90.4%{{opacity:1}}91.2%{{opacity:.3}}92.8%{{opacity:.9}}93.6%{{opacity:.2}}}}
.fg{{animation:fg ease-in-out infinite alternate}}@keyframes fg{{from{{transform:translateX(-60px)}}to{{transform:translateX(60px)}}}}
.sw{{animation:sw ease-in-out infinite alternate}}@keyframes sw{{from{{transform:rotate({-.4 - wind * 1.1:.2f}deg)}}to{{transform:rotate({.3 + wind * 1.6:.2f}deg)}}}}
.la,.lb,.lc{{opacity:0;animation:la ease-in infinite}}.lb{{animation-name:lb}}.lc{{animation-name:lc}}
@keyframes la{{0%{{opacity:0;transform:translate(0,0)}}8%{{opacity:1}}40%{{transform:translate({40 + 90 * wind:.0f}px,10px)}}85%{{opacity:1}}100%{{opacity:0;transform:translate({70 + 170 * wind:.0f}px,95px)}}}}
@keyframes lb{{0%{{opacity:0;transform:translate(0,0)}}8%{{opacity:1}}30%{{transform:translate({20 + 60 * wind:.0f}px,-14px)}}85%{{opacity:1}}100%{{opacity:0;transform:translate({60 + 200 * wind:.0f}px,70px)}}}}
@keyframes lc{{0%{{opacity:0;transform:translate(0,0)}}10%{{opacity:1}}50%{{transform:translate({-10 + 40 * wind:.0f}px,40px)}}85%{{opacity:1}}100%{{opacity:0;transform:translate({10 + 110 * wind:.0f}px,110px)}}}}
.an{{animation:an linear infinite alternate}}@keyframes an{{from{{transform:scaleX(1)}}to{{transform:scaleX(-1)}}}}
.ms{{opacity:0;animation:ms linear infinite}}@keyframes ms{{0%{{opacity:0;transform:translate(0,0)}}1.5%{{opacity:1}}6%{{opacity:0;transform:translate(-190px,76px)}}100%{{opacity:0;transform:translate(-190px,76px)}}}}
.xl{{animation:xl 1.4s steps(2,jump-none) infinite alternate}}@keyframes xl{{from{{opacity:.3}}to{{opacity:1}}}}
.gl{{animation:gl 3.5s ease-in-out infinite alternate}}@keyframes gl{{from{{opacity:.6}}to{{opacity:1}}}}
</style>
<g clip-path="url(#c)">
<rect width="{W}" height="{H}" fill="url(#sky)"/>''')

    # stars
    if nf > 0.05:
        o.append(f'<g opacity="{nf * max(0, 1 - ov * 1.6):.2f}">')
        for _ in range(130):
            x, y, r = rnd.uniform(0, W), rnd.uniform(0, 175), rnd.choice([.5, .6, .7, .9, 1.1, 1.5])
            cls = ' class="tw"' if r > .8 else ""
            o.append(f'<circle{cls} cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="#fff" style="animation-delay:-{rnd.uniform(0, 3):.1f}s"/>')
        o.append('</g>')

    # sun / moon
    hx = W / 2 + max(-1, min(1, ha / 100)) * W * 0.45
    if elev > -4:
        sy = max(34, 150 - max(-4, elev) * (4.6 if R else 165 / 40)) if R else max(48, 200 - max(-4, elev) / 40 * 165)
        o.append(f'<g opacity="{max(.05, 1 - ov * 1.2):.2f}"><circle cx="{hx:.0f}" cy="{sy:.0f}" r="115" fill="url(#halo)"/><circle cx="{hx:.0f}" cy="{sy:.0f}" r="20" fill="#fff6d6"/></g>')
    else:
        mx, my = max(230, W - hx), 60
        o[1] = o[1].replace('cx="0" cy="0" r="0"', f'cx="{mx + 8:.0f}" cy="{my - 5}" r="17"')
        o.append(f'<circle cx="{mx:.0f}" cy="{my}" r="80" fill="url(#halo)" opacity=".45"/><circle cx="{mx:.0f}" cy="{my}" r="18" fill="#eef0ff" mask="url(#cres)" opacity="{max(.08, 1 - ov * 1.3):.2f}"/>')

    # shooting stars, every night when the sky is open
    if nf > .55 and ov < .6:
        mr = random.Random(f"meteor{now_utc:%Y%m%d}")
        for dur in (9, 14, 23):
            x, y = mr.uniform(250, 1150), mr.uniform(15, 70)
            o.append(f'<g class="ms" style="animation-duration:{dur}s;animation-delay:-{mr.uniform(0, dur):.1f}s">'
                     f'<path d="M{x:.0f} {y:.0f} l75 -30" stroke="url(#met)" stroke-width="1.6" stroke-linecap="round"/>'
                     f'<circle cx="{x:.0f}" cy="{y:.0f}" r="1.6" fill="#fff"/><circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="#fff" opacity=".25"/></g>')

    if R:
        hx_light = (hx - W / 2) / (W / 2) if elev > -4 else (max(230, W - hx) - W / 2) / (W / 2)
        RL = raster_scene(p, haze, elev, nf, ov, season, weather, wind, max(-1.0, min(1.0, hx_light)), now_utc)
        o[1] = o[1].replace("</defs>", RL["defs"] + "</defs>", 1)
        o.append(RL["clouds"])
        if weather == "storm":
            for j, (gx, dur, delay) in enumerate(((180, 5.5, 1), (620, 8.5, 3.2), (1010, 13, 6), (430, 9.5, 7.5))):
                o.append(f'<ellipse class="lt" cx="{gx}" cy="58" rx="150" ry="48" fill="url(#bolt)" '
                         f'style="animation-duration:{dur}s;animation-delay:-{delay}s"/>')
    else:
        # mountains, snow cap depth depends on season
        peaks = [(0, 196), (80, 168), (150, 186), (240, 126), (310, 166), (372, 150), (444, 182), (534, 116),
                 (622, 170), (700, 140), (772, 178), (860, 104), (948, 164), (1018, 134), (1096, 172), (1164, 146), (1200, 160)]
        md = f"M0 {H}"
        for i, (x, y) in enumerate(peaks):
            if i:
                px, py = peaks[i - 1]
                for f in (.33, .66):
                    md += f" L{px + (x - px) * f:.0f} {py + (y - py) * f + rnd.uniform(-4, 4):.0f}"
            md += f" L{x} {y}"
        o.append(f'<path d="{md} L{W} {H}Z" fill="{mix(p["mtn"], haze, .2)}"/>')
        caps = ""
        for i in range(1, len(peaks) - 1):
            x, y = peaks[i]
            d = S["cap"] * (1.0 if y < 140 else 0.6 if y < 170 else 0.25)
            if d < 8:
                continue
            (lx, ly), (rx, ry) = peaks[i - 1], peaks[i + 1]
            a = (x - (x - lx) * min(.95, d / max(1, ly - y)), y + d)
            b = (x + (rx - x) * min(.95, d / max(1, ry - y)), y + d)
            jag = [(a[0] + (b[0] - a[0]) * f, y + d - (d * .3 if j % 2 else 0) + rnd.uniform(-2, 2))
                   for j, f in enumerate((.18, .36, .54, .72, .88))]
            caps += poly([(x, y), a] + jag + [b])
        if caps:
            o.append(f'<path d="{caps}" fill="{p["msnow"]}" opacity=".92"/>')
        # puffy clouds: shadowed base + lit top, drifting at different speeds
        wr = random.Random(f"{weather}-{now_utc:%Y%m%d}")
        n_cl = {"clear": 0 if nf > .5 else 3, "cloudy": 7, "rain": 2, "storm": 0, "fog": 4, "snow": 0}[weather]

        def puff(rr, w):
            """Cumulus: bell-shaped stack of lumps on a soft rounded base, no flat edges."""
            n = rr.randint(7, 11)
            parts, out = [], ""
            for j in range(n):
                t = j / (n - 1)
                bell = math.sin(math.pi * t) ** 0.8
                r = w * (0.07 + 0.13 * bell) * rr.uniform(0.8, 1.2)
                cx = -w / 2 + w * t + rr.uniform(-w * .03, w * .03)
                cy = -r * rr.uniform(0.35, 0.6) - bell * w * 0.06
                parts.append((cx, cy, r))
            for j in range(rr.randint(2, 4)):  # second tier of lumps on top
                cx = rr.uniform(-w * .22, w * .22)
                r = w * rr.uniform(.1, .16)
                parts.append((cx, -w * rr.uniform(.13, .2), r))
            for cx, cy, r in parts:
                out += f"M{cx - r:.1f} {cy:.1f}a{r:.1f} {r:.1f} 0 1 0 {2 * r:.1f} 0a{r:.1f} {r:.1f} 0 1 0 {-2 * r:.1f} 0"
            rx, ry = w * .5, w * .06
            out += f"M{-rx:.1f} 0a{rx:.1f} {ry:.1f} 0 1 0 {2 * rx:.1f} 0a{rx:.1f} {ry:.1f} 0 1 0 {-2 * rx:.1f} 0"
            return out

        for i in range(n_cl):
            y, w = wr.uniform(55, 125), wr.uniform(110, 260)
            cr = random.Random(f"cloud{i}{weather}")
            shape = puff(cr, w)
            lightc = T(mix(mix("#ffffff", "#8a939f", ov * .8), p["mid"], .2 + .55 * nf))
            darkc = T(mix(mix("#c3cedb", "#3f4651", ov), p["mid"], .25 + .5 * nf))
            dur = wr.uniform(160, 300) * (260 / w) ** .3
            o.append(f'<g class="cd" opacity="{.95 if ov else .85}" style="animation-duration:{dur:.0f}s;animation-delay:-{wr.uniform(0, dur):.0f}s">'
                     f'<g transform="translate(0 {y:.0f})"><path d="{shape}" fill="{darkc}"/>'
                     f'<path d="{shape}" fill="{lightc}" transform="translate({-w * .02:.1f} {-w * .035:.1f}) scale(.94 .9)"/></g></g>')
        o.append(f'<rect y="135" width="{W}" height="110" fill="url(#fog)"/>')

        # storm / rain cloud deck: three seamless layers rolling at different speeds
        if weather in ("rain", "storm", "snow"):
            storm = weather == "storm"

            def deck_path(seed, yb, amp, rmin, rmax):
                rr = random.Random(seed)
                radii = []
                while sum(2 * r for r in radii) < W:
                    radii.append(rr.uniform(rmin, rmax))
                k = W / sum(2 * r for r in radii)
                radii = [r * k for r in radii]
                ys = [yb + rr.uniform(-amp, amp) for _ in radii]
                n = len(radii)
                d, x = f"M0 -5 H{2 * W} V{ys[-1]:.1f}", 2 * W
                for _ in range(2):
                    for i in range(n - 1, -1, -1):
                        r = radii[i]
                        x -= 2 * r
                        d += f" A{r:.1f} {r * .62:.1f} 0 0 1 {x:.1f} {ys[i - 1]:.1f}"
                return d + " V-5Z"

            top_c = mix("#7d8693" if storm else "#c9d0d8" if weather == "snow" else "#b3bcc7", "#141821", nf)
            bot_c = mix("#2f3540" if storm else "#a2abb6" if weather == "snow" else "#7b8592", "#07090d", nf)
            layers = [(98, 10, 24, 42, 170, .55), (84, 13, 30, 56, 115, .8), (66, 11, 38, 66, 75, 1)]
            for li, (yb, amp, r1, r2, dur, op) in enumerate(layers):
                o[1] = o[1].replace("</defs>", f'<linearGradient id="dk{li}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="{yb + amp}">'
                                    f'<stop offset="0" stop-color="{mix(top_c, bot_c, li * .2)}"/><stop offset="1" stop-color="{mix(bot_c, top_c, .15 * (2 - li))}"/></linearGradient></defs>', 1)
                dur = dur / (1.5 if storm else 1)
                o.append(f'<g class="dk" style="animation-duration:{dur:.0f}s"><path d="{deck_path(f"deck{li}", yb, amp, r1, r2)}" fill="url(#dk{li})" opacity="{op}"/></g>')
            # ragged scud racing under the deck
            for j in range(9 if storm else 6):
                yy, rx = wr.uniform(92, 128), wr.uniform(40, 95)
                dur = wr.uniform(35, 60) / (1.4 if storm else 1)
                o.append(f'<ellipse class="cd" cx="0" cy="{yy:.0f}" rx="{rx:.0f}" ry="{rx * wr.uniform(.08, .14):.0f}" fill="{bot_c}" '
                         f'opacity="{wr.uniform(.2, .35):.2f}" style="animation-duration:{dur:.0f}s;animation-delay:-{wr.uniform(0, dur):.0f}s"/>')
            # lightning glowing inside the clouds
            if storm:
                for j, (gx, dur, delay) in enumerate(((180, 5.5, 1), (620, 8.5, 3.2), (1010, 13, 6), (430, 9.5, 7.5))):
                    o.append(f'<ellipse class="lt" cx="{gx}" cy="58" rx="150" ry="48" fill="url(#bolt)" '
                             f'style="animation-duration:{dur}s;animation-delay:-{delay}s"/>')

    # lightning: jagged bolts with branches, strike behind the treeline
    flashes = []
    if weather == "storm":
        lr = random.Random(f"bolt-{now_utc:%Y%m%d%H}")

        def walk(x, y, y_end, step, spread):
            pts = [(x, y)]
            while y < y_end:
                y += lr.uniform(step * .6, step * 1.2)
                x += lr.uniform(-spread, spread)
                pts.append((x, min(y, y_end)))
            return pts

        for i, (bx, dur, delay) in enumerate(((lr.uniform(220, 420), 7, 0), (lr.uniform(560, 760), 11, 4.5))):
            main = walk(bx, 95, 232, 9, 7)
            paths = ["M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in main)]
            for _ in range(3):
                sx, sy = main[lr.randint(2, len(main) // 2)]
                br = walk(sx, sy, sy + lr.uniform(25, 55), 7, 6)
                drift = lr.choice([-1, 1]) * lr.uniform(2, 4)
                br = [(x + drift * k, y) for k, (x, y) in enumerate(br)]
                paths.append("M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in br))
            d = " ".join(paths)
            st = f"animation-duration:{dur}s;animation-delay:-{delay}s"
            flashes.append(st)
            o.append(f'<g class="lt" style="{st}" fill="none" stroke-linecap="round" stroke-linejoin="round">'
                     f'<circle cx="{bx:.0f}" cy="100" r="150" fill="url(#bolt)"/>'
                     f'<path d="{d}" stroke="#9fb8ff" stroke-width="7" opacity=".25"/>'
                     f'<path d="{d}" stroke="#d8e4ff" stroke-width="3" opacity=".6"/>'
                     f'<path d="{paths[0]}" stroke="#ffffff" stroke-width="1.6"/>'
                     f'<path d="{" ".join(paths[1:])}" stroke="#ffffff" stroke-width=".9"/></g>')

    # canopy rows (far -> near). tower sits between row 2 and 3
    light = -1 if hx < W / 2 else 1
    lk = .2 * (1 - nf * .85)
    spawn = []
    if R:
        o.append(RL["terrain"])
        o.append(RL["low"])
        o.append(RL["mid"])
    else:
        rows = [(206, 18, 32, .24, 7, .72, 0), (224, 26, 46, .24, 9.5, .54, 0), (246, 36, 62, .23, 13, .36, 20)]
        for i, r in enumerate(rows):
            o.append(canopy(rnd, *r[:6], S, haze, T, bloom_n=r[6], light=light, lk=lk))
            o.append(f'<rect y="{r[0] - 30}" width="{W}" height="50" fill="url(#fog)" opacity="{.75 if season == "autumn" else .5}"/>')

    # ---- fire lookout: steel lattice tower, glass cab, flat roof ----
    cx = 905
    lit = elev < 4 or ov >= .6
    steel, steel2 = T("#2a2e33"), T(mix("#2a2e33", haze, .35))
    wall, roofc = T("#e8e4d8"), T("#3a3e43")
    y0, yb = 134, 330
    hw = lambda y: 34 + (y - y0) * (18 / (yb - y0))
    tw = []
    # back legs (lighter, further away)
    tw.append(f'<path d="M{cx - 20} {y0} L{cx - 30} {yb} M{cx + 20} {y0} L{cx + 30} {yb}" stroke="{steel2}" stroke-width="2.2"/>')
    # stairs zig-zag inside
    st = ""
    flights = [(y0 + 4 + i * 22, i % 2) for i in range(9)]
    for y, flip in flights:
        a1, a2 = (-1, 1) if flip else (1, -1)
        st += f"M{cx + a1 * hw(y) * .55:.1f} {y} L{cx + a2 * hw(y + 22) * .55:.1f} {y + 22}"
        st += f"M{cx + a1 * hw(y) * .55:.1f} {y - 5} L{cx + a2 * hw(y + 22) * .55:.1f} {y + 17}"
    tw.append(f'<path d="{st}" stroke="{steel2}" stroke-width="1.3" fill="none"/>')
    # front legs, girts, X braces
    levels = [y0, 172, 212, 256, 304, yb]
    br = f"M{cx - hw(y0):.1f} {y0} L{cx - hw(yb):.1f} {yb} M{cx + hw(y0):.1f} {y0} L{cx + hw(yb):.1f} {yb}"
    xb = ""
    for y1, y2 in zip(levels, levels[1:]):
        w1, w2 = hw(y1), hw(y2)
        xb += f"M{cx - w1:.1f} {y1} L{cx + w2:.1f} {y2} M{cx + w1:.1f} {y1} L{cx - w2:.1f} {y2} M{cx - w2:.1f} {y2} H{cx + w2:.1f}"
    tw.append(f'<path d="{br}" stroke="{steel}" stroke-width="3.6"/><path d="{xb}" stroke="{steel}" stroke-width="1.4" fill="none"/>')
    # solar panel on the left leg
    sx = cx - hw(150)
    tw.append(f'<path d="M{sx - 1:.1f} 146 L{sx - 15:.1f} 149 L{sx - 15:.1f} 176 L{sx - 1:.1f} 172Z" fill="{T("#1c2838")}"/>'
              f'<path d="M{sx - 8:.1f} 147.5 V174 M{sx - 1:.1f} 159 L{sx - 15:.1f} 162" stroke="{T("#4a6a8c")}" stroke-width=".7"/>')
    o.append("<g>" + "".join(tw) + "</g>")
    if lit:
        o.append(f'<circle class="gl" cx="{cx}" cy="110" r="{70 + 40 * nf:.0f}" fill="url(#warm)" opacity="{.35 + .65 * nf:.2f}"/>')
    glass = "#ffc96e" if lit else T(mix("#26303a", p["bot"], .18))
    mull = "".join(f"M{cx - 38 + i * 7.6:.1f} 101 v20" for i in range(1, 10))
    rail_posts = "".join(f"M{cx - 50 + i * 10:.0f} 116 v16" for i in range(11))
    an_dur = max(.12, .6 - wind * .3)
    o.append(f'''<g>
<rect x="{cx - 38}" y="96" width="76" height="36" fill="{wall}"/>
<rect x="{cx - 38}" y="101" width="76" height="20" fill="{glass}"/>
{'' if lit else f'<path d="M{cx - 30} 121 L{cx - 18} 101 H{cx - 12} L{cx - 24} 121Z M{cx + 6} 121 L{cx + 18} 101 H{cx + 21} L{cx + 9} 121Z" fill="#ffffff" opacity=".13"/>'}
<path d="M{cx + 4} 121 v-6 a4 4 0 0 1 8 0 v6Z M{cx + 5} 112 a3 3 0 1 1 6 0 a3 3 0 1 1 -6 0Z" fill="{T("#15110e")}"/>
<path d="{mull}" stroke="{T("#c9c4b6")}" stroke-width="1.2"/>
<rect x="{cx - 51}" y="132" width="102" height="4" fill="{steel}"/>
<path d="M{cx - 50} 116 H{cx + 50} M{cx - 50} 124 H{cx + 50} {rail_posts}" stroke="{steel}" stroke-width="1.3"/>
<path d="M{cx - 48} 96 H{cx + 48} L{cx + 46} 90 H{cx - 46}Z" fill="{roofc}"/>
<rect x="{cx - 48}" y="96" width="96" height="1.6" fill="{wall}" opacity=".6"/>
{f'<path d="M{cx - 49} 91 q0 -5 6 -5 H{cx + 43} q6 0 6 5Z" fill="{T("#eef3fa", .8)}"/>' if season == "winter" else ''}
<path d="M{cx - 22} 90 V80 M{cx + 16} 90 V60 M{cx + 11} 72 H{cx + 21}" stroke="{steel}" stroke-width="1.4"/>
<path class="fl" d="M{cx + 17} 63 q6 -1.5 11 1 q3 1 6 0 v7 q-3 1 -6 0 q-5 -2.5 -11 -1Z" fill="{T("#c8402e")}"/>
<g class="an" style="transform-origin:{cx + 16}px 59px;animation-duration:{an_dur:.2f}s"><path d="M{cx + 10} 59 H{cx + 22}" stroke="{steel}" stroke-width="1"/><circle cx="{cx + 10}" cy="59" r="1.5" fill="{steel}"/><circle cx="{cx + 22}" cy="59" r="1.5" fill="{steel}"/></g>
</g>''')

    # christmas lights on the lookout in december
    if xmas:
        cols = ["#ff4d4d", "#ffd34d", "#4dff88", "#4dc3ff"]
        bulbs = []
        for i in range(25):  # roof edge, draped in 4 swags
            t = i / 24
            x = cx - 48 + 96 * t
            bulbs.append((x, 98.5 + 3.5 * abs(math.sin(math.pi * t * 4))))
        for i in range(29):  # railing
            t = i / 28
            bulbs.append((cx - 50 + 100 * t, 116.5 + 2.5 * abs(math.sin(math.pi * t * 5))))
        wire = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in bulbs[:25]) + " M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in bulbs[25:])
        xl = [f'<path d="{wire}" stroke="{steel}" stroke-width=".6" fill="none"/>']
        for j, (x, y) in enumerate(bulbs):
            c = cols[j % 4]
            d = f"animation-delay:-{(j % 3) * .47:.2f}s"
            if nf > .3:
                xl.append(f'<circle class="xl" cx="{x:.1f}" cy="{y:.1f}" r="2.8" fill="{c}" opacity="{.22 * nf:.2f}" style="{d}"/>')
            xl.append(f'<circle class="xl" cx="{x:.1f}" cy="{y:.1f}" r="1" fill="{c}" style="{d}"/>')
        # little tree on the catwalk + star on the mast
        tx = cx - 43
        xl.append(f'<path d="M{tx} 112 L{tx - 7} 124 H{tx - 3} L{tx - 9} 132 H{tx + 9} L{tx + 3} 124 H{tx + 7}Z" fill="{T("#1f5a3a")}"/>')
        for k, (lx, ly) in enumerate(((tx - 3, 121), (tx + 3, 125), (tx - 5, 129), (tx + 4, 130), (tx, 117))):
            xl.append(f'<circle class="xl" cx="{lx}" cy="{ly}" r="1.2" fill="{cols[k % 4]}" style="animation-delay:-{k * .3:.1f}s"/>')
        sp = []
        for k in range(10):
            a = -math.pi / 2 + k * math.pi / 5
            rr = 4.5 if k % 2 == 0 else 2
            sp.append((cx + 16 + rr * math.cos(a), 54 + rr * math.sin(a)))
        xl.append(f'<circle class="gl" cx="{cx + 16}" cy="54" r="12" fill="url(#halo)"/><path d="{poly(sp)}" fill="#ffd45e"/>')
        o.append("<g>" + "".join(xl) + "</g>")

    # near rows hide the bottom of the tower
    if R:
        o.append(RL["front"])
        spawn = RL["spawn"]
    else:
        for r in [(274, 52, 88, .22, 18, .16, 26), (306, 74, 124, .22, 25, 0, 30)]:
            o.append(canopy(rnd, *r[:6], S, haze, T, bloom_n=r[6], light=light, lk=lk, sway=True, spawn=spawn))

    # birds (daylight, not deep winter)
    if nf < .55 and ov < .6:
        for gi in range(2 if season != "winter" else 1):
            dur, y0 = rnd.uniform(38, 55), rnd.uniform(70, 120)
            o.append(f'<g class="bd" style="animation-duration:{dur:.0f}s;animation-delay:-{rnd.uniform(0, dur):.0f}s">')
            for b in range(rnd.randint(3, 5)):
                bx, by = b * 14 + rnd.uniform(-4, 4), y0 + rnd.uniform(-9, 9)
                o.append(f'<path class="wg" style="animation-delay:-{rnd.uniform(0, .45):.2f}s" d="M{bx-6:.0f} {by-2:.0f} q3 -3 6 1 q3 -4 6 -1" stroke="{T("#2b2f3a")}" stroke-width="1.5" fill="none"/>')
            o.append('</g>')

    # handle
    o.append(f'<text x="30" y="38" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
             f'font-size="13" letter-spacing="5" fill="#ffffff" opacity=".75">{name}</text>')

    # season particles
    def falling(n, make, spd=(16, 26), sway="sa"):
        for _ in range(n):
            x, dur = rnd.uniform(-20, W + 20), rnd.uniform(*spd)
            o.append(f'<g class="fa" style="animation-duration:{dur:.1f}s;animation-delay:-{rnd.uniform(0, dur):.1f}s">'
                     f'<g class="{sway}" style="animation-duration:{rnd.uniform(2.5, 5):.1f}s;animation-delay:-{rnd.uniform(0, 5):.1f}s">'
                     f'{make(x)}</g></g>')

    if weather == "snow":
        for n, a, b, op, spd, sw in ((120, .7, 1.3, .55, (14, 22), "sa"), (80, 1.4, 2.3, .8, (9, 14), "sa"), (30, 2.6, 4.0, .95, (5.5, 8.5), "sb")):
            falling(n, lambda x, a=a, b=b, op=op: f'<circle cx="{x:.0f}" cy="0" r="{rnd.uniform(a, b):.1f}" fill="#fff" opacity="{op}"/>', spd, sw)
    elif season in ("autumn", "spring") and spawn:
        autumn = season == "autumn"
        cols = ["#e0892b", "#cf5a2e", "#e8b440", "#b8412c"] if autumn else ["#f7c3d4", "#ffffff", "#f3a9c2"]
        n = int((28 if autumn else 16) * (1 + wind))
        for _ in range(n):
            x, y = rnd.choice(spawn)
            x += rnd.uniform(-14, 14)
            dur = rnd.uniform(5, 9) / (1 + wind * .8)
            shape = (f'<path class="sp" style="animation-duration:{rnd.uniform(1.5, 4):.1f}s" d="M-4 0 q4 -4 8 0 q-4 4 -8 0Z" fill="{T(rnd.choice(cols))}"/>'
                     if autumn else
                     f'<ellipse class="sp" style="animation-duration:{rnd.uniform(2, 5):.1f}s" rx="2.6" ry="1.5" fill="{T(rnd.choice(cols))}"/>')
            o.append(f'<g transform="translate({x:.0f} {y:.0f})"><g class="{rnd.choice(["la", "lb", "lc"])}" '
                     f'style="animation-duration:{dur:.1f}s;animation-delay:-{rnd.uniform(0, dur):.1f}s">{shape}</g></g>')
    if season in ("summer", "spring") and nf > .45 and weather in ("clear", "cloudy"):
        for _ in range(30 if season == "summer" else 12):
            x, y = rnd.uniform(0, W), rnd.uniform(215, 300)
            o.append(f'<circle class="ff" cx="{x:.0f}" cy="{y:.0f}" r="1.6" fill="#e9ff8a" '
                     f'style="animation-duration:{rnd.uniform(2, 4):.1f}s;animation-delay:-{rnd.uniform(0, 4):.1f}s"/>')

    # weather effects
    if weather in ("rain", "storm"):
        for _ in range(140 if weather == "storm" else 95):
            x, dur = rnd.uniform(-20, W + 60), rnd.uniform(.55, 1.0)
            o.append(f'<path class="rn" d="M{x:.0f} 0 l-4 14" stroke="#cfd9e6" stroke-width="{rnd.uniform(.8, 1.4):.1f}" '
                     f'opacity="{rnd.uniform(.35, .7):.2f}" style="animation-duration:{dur:.2f}s;animation-delay:-{rnd.uniform(0, dur):.2f}s"/>')
    for st in flashes:
        o.append(f'<g class="lt" style="{st}"><rect width="{W}" height="{H}" fill="#dfe8ff" opacity=".2"/></g>')
    if weather == "fog" and R:
        o.append(f'<rect width="{W}" height="{H}" fill="{haze}" opacity=".18"/>')
    elif weather == "fog":
        o.append(f'<rect width="{W}" height="{H}" fill="{haze}" opacity=".32"/>')
        for i, (y, h, op) in enumerate(() if R else ((120, 110, .9), (185, 100, 1), (245, 100, .85))):
            o.append(f'<rect class="fg" x="-80" y="{y}" width="{W + 160}" height="{h}" fill="url(#fog)" opacity="{op}" '
                     f'style="animation-duration:{14 + i * 5}s;animation-delay:-{i * 4}s"/>')

    if R:
        o.append(f'<rect width="{W}" height="{H}" fill="url(#vg)"/>'
                 f'<rect width="{W}" height="{H}" filter="url(#gr)" opacity=".07" style="mix-blend-mode:overlay"/>')
    o.append(f'<text x="31" y="56" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="10" '
             f'letter-spacing="3" fill="#ffffff" opacity=".55">{SEASON_NAME[season].upper()} \u00b7 {weather.upper()}</text>')
    o.append('</g></svg>')
    return "\n".join(o)


def load_config(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def apply_config(cfg, now):
    """Turn config.json into build() arguments. An expired override is ignored."""
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    kw = dict(name=cfg.get("name") or owner or "LOOKOUT",
              lat=cfg.get("lat"), lon=cfg.get("lon"))
    ov = cfg.get("override") or {}
    until = ov.get("until")
    if ov and (not until or datetime.fromisoformat(until.replace("Z", "+00:00")) > now):
        w = LEGACY_WEATHER.get(ov.get("weather"), ov.get("weather"))
        if w in OVERCAST:
            kw["weather"] = w
        if ov.get("season") == "december":
            kw["season"], kw["xmas"] = "winter", True
        elif ov.get("season") in SEASON:
            kw["season"] = ov["season"]
        if ov.get("hour") is not None:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(cfg.get("tz") or "Europe/Zurich")
            h = float(ov["hour"]) % 24
            local = now.astimezone(tz).replace(hour=int(h), minute=int(h % 1 * 60), second=0, microsecond=0)
            now = local.astimezone(timezone.utc)
    return now, kw


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    path = sys.argv[1] if len(sys.argv) > 1 else "banner.svg"
    if len(sys.argv) > 2:  # preview: generate.py out.svg 2026-11-04T22:00 [season] [weather]
        now = datetime.fromisoformat(sys.argv[2]).replace(tzinfo=timezone.utc)
        kw = dict(season=sys.argv[3] if len(sys.argv) > 3 else None,
                  weather=sys.argv[4] if len(sys.argv) > 4 else None, name="FLACO2009")
    else:
        now, kw = apply_config(load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")), now)
    with open(path, "w") as f:
        f.write(build(now, **kw))
    print(f"wrote {path}")
