"""Realistic raster layers for the Lookout banner.

Everything is procedural: a heightfield made of noise is ray-cast column by
column (voxel-space style) into a G-buffer once, then shaded for the current
sun, season and weather. Clouds, fog and the foreground firs are painted the
same way. Needs numpy and Pillow; generate.py falls back to flat vector art
when they are missing.
"""
import base64
import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------- noise
_U32 = np.uint32


def _hash(ix, iy, seed):
    h = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = h.astype(np.uint64)
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return (h & 0xFFFFFF).astype(np.float32) / float(0xFFFFFF)


def vnoise(x, y, seed=0, period=None):
    """Smooth value noise in [0,1]. Optional horizontal period makes it tile."""
    xi = np.floor(x)
    yi = np.floor(y)
    fx = (x - xi).astype(np.float32)
    fy = (y - yi).astype(np.float32)
    xi = xi.astype(np.int64)
    yi = yi.astype(np.int64)
    x1 = xi + 1
    if period:
        xi = np.mod(xi, period)
        x1 = np.mod(x1, period)
    ux = fx * fx * (3 - 2 * fx)
    uy = fy * fy * (3 - 2 * fy)
    a = _hash(xi, yi, seed)
    b = _hash(x1, yi, seed)
    c = _hash(xi, yi + 1, seed)
    d = _hash(x1, yi + 1, seed)
    return (a + (b - a) * ux) + ((c + (d - c) * ux) - (a + (b - a) * ux)) * uy


def fbm(x, y, octaves=5, seed=0, lac=2.0, gain=0.5, period=None):
    amp, tot, norm = 1.0, 0.0, 0.0
    for o in range(octaves):
        tot = tot + amp * vnoise(x, y, seed + o * 17, period * (lac ** o) if period else None)
        norm += amp
        x = x * lac
        y = y * lac
        amp *= gain
    return tot / norm


def ridged(x, y, octaves=6, seed=0):
    amp, tot, norm, w = 1.0, 0.0, 0.0, 1.0
    for o in range(octaves):
        n = 1.0 - np.abs(vnoise(x, y, seed + o * 31) * 2 - 1)
        n = n * n * w
        w = np.clip(n * 1.6, 0, 1)
        tot = tot + amp * n
        norm += amp
        x = x * 2.03
        y = y * 2.03
        amp *= 0.5
    return tot / norm


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- terrain
CAM_H = 150.0
W0, H0, HORIZON, FOV = 1200, 320, 0.47, 1.05


def height(x, y):
    """World height. Camera at origin looking +y (towards the alps)."""
    far = smooth(6500, 9500, y)
    alps = ridged(x / 2600 + 3.1, y / 2600 + 7.7, 7, seed=11) ** 1.2 * 1350 * far
    alps += fbm(x / 800, y / 800, 3, seed=5) * 120 * far
    pre = smooth(3200, 4600, y) * (1 - smooth(6000, 7500, y))
    prealps = (ridged(x / 1500 + 1.7, y / 1500, 6, seed=29) ** 1.3) * 560 * pre
    mid = (fbm(x / 600 + 9, y / 600, 5, seed=23) ** 1.6) * 260 * smooth(900, 2000, y) * (1 - smooth(3000, 4200, y))
    near = (fbm(x / 340 + 4, y / 340, 4, seed=41) ** 1.2) * 150 * smooth(160, 420, y) * (1 - smooth(650, 1200, y))
    valley = -80 * smooth(700, 1300, y) * (1 - smooth(2200, 3400, y))
    return alps + prealps + mid + near + valley


def build_gbuffer(w=W0, h=H0, steps=520, zmin=10.0, zmax=26000.0, refine=9):
    """Ray-cast once (slow, offline). Returns dict of per-pixel maps."""
    focal = w / (2 * math.tan(FOV / 2))
    hor = h * HORIZON
    ang = (np.arange(w, dtype=np.float32) / (w - 1) - .5) * FOV
    dx, dy, ca = np.sin(ang), np.cos(ang), np.cos(ang)
    ybuf = np.full(w, h, dtype=np.float32)
    K = np.full((h, w), -1, np.int32)
    rows = np.arange(h, dtype=np.float32)[:, None]
    zs = (zmin * (zmax / zmin) ** (np.arange(steps) / (steps - 1))).astype(np.float32)
    for k, z in enumerate(zs):
        hh = height(dx * z, dy * z)
        sy = np.maximum(hor - (hh - CAM_H) / (z * ca) * focal, -1)
        m = (rows >= sy[None, :]) & (rows < ybuf[None, :])
        K[m] = k
        ybuf = np.minimum(ybuf, sy)
    mask = K >= 0
    r, c = np.nonzero(mask)
    k = K[r, c]
    lo = np.where(k > 0, zs[np.maximum(k - 1, 0)], zmin * .5).astype(np.float64)
    hi = zs[k].astype(np.float64)
    slope_r = (hor - r) / focal * ca[c]
    sx, sy_ = dx[c], dy[c]
    for _ in range(refine):  # bisection: ray above terrain at lo, below at hi
        mid = (lo + hi) * .5
        above = CAM_H + slope_r * mid > height(sx * mid, sy_ * mid)
        lo = np.where(above, mid, lo)
        hi = np.where(above, hi, mid)
    z = (lo + hi) * .5
    px, py = sx * z, sy_ * z
    e = np.maximum(1.5, z * .003)
    hx = height(px + e, py) - height(px - e, py)
    hy = height(px, py + e) - height(px, py - e)
    n = np.stack([-hx, 2 * e, -hy], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    out = dict(Z=np.zeros((h, w), np.float32), H=np.zeros((h, w), np.float32), N=np.zeros((h, w, 3), np.float32),
               T=np.zeros((h, w, 3), np.float32))
    out["Z"][r, c] = z
    out["H"][r, c] = height(px, py)
    out["N"][r, c] = n
    out["T"][r, c, 0] = fbm(px / 6, py / 6, 3, seed=77)
    out["T"][r, c, 1] = fbm(px / 110, py / 110, 4, seed=91)
    out["T"][r, c, 2] = fbm(px / 200, py / 200, 4, seed=13)
    return out


def save_gbuffer(g, folder):
    import os
    os.makedirs(folder, exist_ok=True)
    zq = np.where(g["Z"] > 0, np.clip(np.log(np.maximum(g["Z"], 1)) / math.log(30000) * 65534 + 1, 1, 65535), 0)
    Image.fromarray(zq.astype(np.uint16)).save(f"{folder}/depth.png", optimize=True)
    hq = np.clip((g["H"] + 200) / 2000 * 65535, 0, 65535)
    Image.fromarray(hq.astype(np.uint16)).save(f"{folder}/height.png", optimize=True)
    Image.fromarray(((g["N"] * .5 + .5) * 255).round().astype(np.uint8), "RGB").save(f"{folder}/normal.png", optimize=True)
    Image.fromarray((np.clip(g["T"], 0, 1) * 255).round().astype(np.uint8), "RGB").save(f"{folder}/tex.png", optimize=True)


class GBuffer:
    def __init__(self, folder):
        zq = np.asarray(Image.open(f"{folder}/depth.png"), np.float32)
        self.mask = zq > 0
        self.Z = np.where(self.mask, np.exp((zq - 1) / 65534 * math.log(30000)), 0).astype(np.float32)
        self.HH = np.asarray(Image.open(f"{folder}/height.png"), np.float32) / 65535 * 2000 - 200
        n = np.asarray(Image.open(f"{folder}/normal.png"), np.float32) / 255 * 2 - 1
        self.N = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
        t = np.asarray(Image.open(f"{folder}/tex.png"), np.float32) / 255
        self.tex, self.tex2, self.snoise = t[..., 0], t[..., 1], t[..., 2]
        self.h, self.w = self.Z.shape


def hexrgb(c):
    return np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], np.float32) / 255


def mixc(a, b, t):
    return a + (b - a) * t


SEASON_MAT = {
    "spring": dict(forest=["#2f5a36", "#3d6e3c"], meadow="#8fb85a", decid=("#7db352", .30), snow=900, frost=0),
    "summer": dict(forest=["#1f4430", "#2a5236"], meadow="#9aa84c", decid=("#3f7a35", .25), snow=1150, frost=0),
    "autumn": dict(forest=["#24402f", "#2d4a33"], meadow="#b39a4a", decid=("#d98a2b", .38), snow=820, frost=0),
    "winter": dict(forest=["#20352f", "#273d35"], meadow="#d9e2ec", decid=("#6b5a4a", .2), snow=-50, frost=.55),
}


def shade_terrain(G, season, sun, light, haze, amb, fog_k, snow_boost=0.0, valley_fog=0.25):
    """sun: dict(elev, x) ; light: rgb sun color ; amb: rgb ambient ; haze rgb."""
    M = SEASON_MAT[season]
    n = G.N
    h = G.HH
    slope = n[..., 1]
    rock = mixc(hexrgb("#6f6a66"), hexrgb("#8b857c"), G.tex2[..., None])
    f1, f2 = hexrgb(M["forest"][0]), hexrgb(M["forest"][1])
    crowns = np.clip(G.tex, 0, 1) ** 1.6
    crowns = mixc(crowns, np.full_like(crowns, .45), smooth(1500, 7000, G.Z))
    forest = mixc(f1, f2, G.tex2[..., None]) * (0.32 + 1.15 * crowns[..., None])
    dcol, dfrac = M["decid"]
    decid_mask = (G.tex2 > 1 - dfrac).astype(np.float32)[..., None] * smooth(.45, .6, G.tex)[..., None]
    forest = mixc(forest, hexrgb(dcol) * (0.35 + 0.9 * crowns[..., None]), decid_mask * .55 * smooth(9000, 2500, G.Z)[..., None])
    meadow = hexrgb(M["meadow"]) * (0.85 + 0.3 * G.tex2[..., None])
    treeline = 620 + 160 * G.snoise
    alb = forest
    alb = mixc(alb, meadow, (smooth(.55, .7, G.tex2) * (1 - smooth(260, 300, G.Z)) * smooth(.7, .9, slope))[..., None] * .7)
    alb = mixc(alb, rock, smooth(treeline - 60, treeline + 60, h)[..., None])
    alb = mixc(alb, rock, smooth(.75, .55, slope)[..., None] * smooth(200, 400, h)[..., None])
    snowline = M["snow"] - snow_boost + 260 * (G.snoise - .5)
    snow = smooth(snowline - 40, snowline + 60, h) * smooth(.42, .62, slope)
    if M["frost"] or snow_boost > 400:
        frost = max(M["frost"], .45 if snow_boost > 400 else 0)
        snow = np.maximum(snow, frost * smooth(.35, .75, G.tex) * smooth(.5, .8, slope))
    snowc = hexrgb("#f4f7fb")
    alb = mixc(alb, snowc, snow[..., None])
    alb = mixc(alb, alb.mean(-1, keepdims=True), smooth(4000, 20000, G.Z)[..., None] * .5)
    # light
    L = np.array([sun["x"], max(.08, math.sin(math.radians(max(sun["elev"], 2)))), .45], np.float32)
    L /= np.linalg.norm(L)
    diff = np.clip((n * L).sum(-1), 0, 1)[..., None]
    sky = np.clip(n[..., 1], 0, 1)[..., None]
    col = alb * (amb * (0.55 + 0.45 * sky) + light * diff)
    # specular-ish sheen on snow
    col += snow[..., None] * light * (diff ** 6) * .25
    # aerial perspective + valley fog
    fz = 1 - np.exp(-(G.Z * fog_k) ** 1.25)
    low = smooth(120, -60, h) * smooth(500, 1600, G.Z) * valley_fog
    f = np.clip(fz + low, 0, .97)[..., None]
    col = mixc(col, haze, f)
    a = G.mask.astype(np.float32)
    return np.concatenate([np.clip(col, 0, 1), a[..., None]], -1)


# ---------------------------------------------------------------- clouds / fog
def cloud_layer(w, h, coverage, sun_x, lit, dark, alpha, seed=3, stretch=3.0):
    """Horizontally tileable cloud band (period = w)."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    per = 6
    u = xs / w * per
    v = ys / h * per / stretch * 1.6
    d = fbm(u, v, 6, seed=seed, period=per)
    d2 = fbm(u + .07 * sun_x, v - .05, 6, seed=seed, period=per)
    thr = 1 - coverage
    dens = smooth(thr, thr + .22, d)
    vert = smooth(0, .25, ys / h) * smooth(1, .55, ys / h)
    dens *= vert
    shade = np.clip((d - d2) * 6 + .55, 0, 1)[..., None]
    col = mixc(dark, lit, shade)
    return np.concatenate([col, (dens * alpha)[..., None]], -1)


def fog_layer(w, h, amount, color, seed=8):
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    per = 5
    d = fbm(xs / w * per, ys / h * 2.2, 5, seed=seed, period=per)
    band = smooth(0, .45, ys / h) * smooth(1, .5, ys / h)
    a = np.clip((d - .32) * 2.4, 0, 1) * band * amount
    col = np.broadcast_to(color, (h, w, 3))
    return np.concatenate([col, a[..., None]], -1)


# ---------------------------------------------------------------- foreground firs
def fir_band(w, h, base_y, hmin, hmax, count, colors, light, sun_x, haze, haze_k, snow, autumn, rng, blur=0.0,
             ss=2, spawn=None, scale=1.0):
    """Tall spire firs (subalpine fir look): ragged branch tufts, lit and shadow side."""
    W, Hh = w * ss, h * ss
    img = Image.new("RGBA", (W, Hh), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)

    def c255(c, a=255):
        c = np.clip(c, 0, 1)
        return (int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), a)

    xs = rng.uniform(-30, w + 30, count)
    hs = rng.uniform(0, 1, count) ** 1.6 * (hmax - hmin) + hmin
    order = np.argsort(hs)  # small (far) first, tall in front
    lit_side = 1 if sun_x >= 0 else -1
    for i in order:
        x, th = xs[i], hs[i]
        by = base_y + rng.uniform(-8, 12) * scale + (1 - (th - hmin) / max(1, hmax - hmin)) * -10 * scale
        base = hexrgb(colors[rng.integers(len(colors))]) * rng.uniform(.85, 1.1)
        larch = autumn and rng.random() < .2
        if larch:
            base = hexrgb(["#c9862a", "#b8702a", "#d4a23a"][rng.integers(3)])
        depth = haze_k * (1.2 - .4 * (th - hmin) / max(1, hmax - hmin))
        dark = mixc(base * .5, haze, depth)
        mid = mixc(base * .8, haze, depth)
        lit = mixc(np.clip(base * (.75 + .45 * light), 0, 1), haze, depth)
        sc = mixc(np.array([.92, .95, .99]) * (.55 + .45 * min(1, light.mean() * 1.2)), haze, depth)
        lean = rng.uniform(-.04, .04)
        wmax = th * rng.uniform(.12, .17)
        dr.line([(x * ss, (by - th * .1) * ss), (x * ss, (by + 30) * ss)], fill=c255(dark * .7), width=max(1, int(th * .018 * ss)))
        y = by - th
        while y < by:
            t = (y - (by - th)) / th
            cx = x + lean * (by - y)
            ww = wmax * (t ** .75) * rng.uniform(.6, 1.25) + .8 * scale
            tuft = max(1.5, th * rng.uniform(.03, .055))
            for side in (-1, 1):
                if rng.random() < .07 and t > .15:
                    continue  # gap in the crown
                tip = (cx + side * ww, y + tuft * rng.uniform(.4, 1.0))
                col = lit if side == lit_side else dark
                dr.polygon([(cx * ss, (y - tuft * .4) * ss), (tip[0] * ss, tip[1] * ss),
                            ((cx + side * ww * .25) * ss, (y + tuft) * ss)], fill=c255(col * rng.uniform(.9, 1.08)))
                if rng.random() < .5:
                    dr.polygon([((cx + side * ww * .1) * ss, y * ss), ((cx + side * ww * .7) * ss, (y + tuft * .7) * ss),
                                ((cx + side * ww * .2) * ss, (y + tuft * .9) * ss)], fill=c255(mid))
                if snow and rng.random() < .75:
                    dr.polygon([(cx * ss, (y - tuft * .45) * ss), ((tip[0] - side * 1) * ss, (tip[1] - tuft * .35) * ss),
                                ((cx + side * ww * .45) * ss, (y + tuft * .15) * ss)], fill=c255(sc))
            y += tuft * rng.uniform(.55, .8)
        if spawn is not None:
            spawn.append((float(x), float(by - th * .5)))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur * ss))
    return img.resize((w, h), Image.LANCZOS)


# ---------------------------------------------------------------- encode
def to_webp_uri(arr_or_img, q=80):
    img = arr_or_img if isinstance(arr_or_img, Image.Image) else Image.fromarray((np.clip(arr_or_img, 0, 1) * 255).astype(np.uint8), "RGBA")
    buf = io.BytesIO()
    try:
        img.save(buf, "WEBP", quality=q, method=4, alpha_quality=80)
        kind = "webp"
    except Exception:  # Pillow without webp (some browsers builds): png still works
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=False, compress_level=3)
        kind = "png"
    return f"data:image/{kind};base64," + base64.b64encode(buf.getvalue()).decode()


_GCACHE = {}


def gbuffer(folder):
    if folder not in _GCACHE:
        _GCACHE[folder] = GBuffer(folder)
    return _GCACHE[folder]


if __name__ == "__main__":  # python terrain.py  -> rebuild assets/terrain
    import os, time
    t = time.time()
    save_gbuffer(build_gbuffer(), os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "terrain"))
    print(f"terrain baked in {time.time() - t:.1f}s")
