"""Dernières transformations des données compactes, appelées par prep.py (et réutilisables seules) :

1. sépare la ligne « TRAM » du GTFS en deux lignes T1 (Hôpital Debré) et T2 (Gare Champagne TGV) ;
2. corrige la couleur du texte des pastilles claires (U2, U23, U24, U25, E2 : texte noir) ;
3. calcule le dessin « en parallèle » des tronçons communs : pour chaque ligne, des tronçons de tracé
   (sans doublon aller/retour) et, en chaque point, une place dans le faisceau (« slot »). Le plan décale
   chaque ligne de slot × écartement, perpendiculairement à son tracé, pour que les lignes qui partagent
   une rue soient côte à côte au lieu de se superposer.

Usage seul : python build/post.py build/data.json   (réécrit le fichier)
"""
import json, math, os, sys
from collections import defaultdict

T1 = {"s": "T1", "l": "Neufchâtel ⇄ Hôpital Debré", "c": "#F80000", "t": "#FFFFFF"}
T2 = {"s": "T2", "l": "Neufchâtel ⇄ Gare Champagne TGV", "c": "#00A2E9", "t": "#FFFFFF"}
DARK_TEXT = {"U2", "U23", "U24", "U25", "E2"}

LAT0 = 49.25
KX = math.cos(math.radians(LAT0))
M = 111320.0  # mètres par degré


def split_tram(data):
    R, PAT, P, Q = data["R"], data["PAT"], data["P"], data["Q"]
    if any(r["s"] == "T1" for r in R):
        return
    t = next((i for i, r in enumerate(R) if r["s"] == "TRAM"), None)
    if t is None:
        return
    base = R[t]
    R[t] = {**base, **T1, "id": base["id"] + "-T1"}
    R.insert(t + 1, {**base, **T2, "id": base["id"] + "-T2"})
    for p in PAT:
        if p[0] > t:
            p[0] += 1
        elif p[0] == t:
            names = [P[Q[q][0]][0] for q in p[4]]
            if any("TGV" in n for n in names):
                p[0] = t + 1


def text_colors(data):
    for r in data["R"]:
        if r["s"] in DARK_TEXT:
            r["t"] = "#1D1D1B"


# ---------- tracés fournis par l'utilisateur (build/traces/<ligne>.kml, .gpx ou .geojson) ----------
# Un fichier par ligne, nommé comme la ligne (T1.kml, U3.kml…). Il peut contenir un ou plusieurs tracés
# (un par sens si l'aller et le retour diffèrent). Pour chaque parcours de la ligne, on prend le tracé
# (dans un sens ou dans l'autre) qui passe le plus près de tous ses arrêts dans l'ordre, et on le coupe
# au premier et au dernier arrêt. Il remplace alors le tracé du GTFS.
TRACES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces")
TRACE_MAX = 60  # m : un arrêt plus loin que ça du tracé → tracé non utilisé pour ce parcours


def read_trace(path):
    import re as _re
    txt = open(path, encoding="utf-8").read()
    lines = []
    if path.endswith(".geojson") or path.endswith(".json"):
        g = json.loads(txt)
        feats = g.get("features", [g])
        for f in feats:
            geo = f.get("geometry", f)
            if geo["type"] == "LineString":
                lines.append([(c[0], c[1]) for c in geo["coordinates"]])
            elif geo["type"] == "MultiLineString":
                lines += [[(c[0], c[1]) for c in l] for l in geo["coordinates"]]
    elif path.endswith(".gpx"):
        for seg in _re.findall(r"<(?:trkseg|rte)>(.*?)</(?:trkseg|rte)>", txt, _re.S):
            pts = _re.findall(r'<(?:trkpt|rtept)[^>]*lat="([-\d.]+)"[^>]*lon="([-\d.]+)"', seg)
            pts += [(a, b) for b, a in _re.findall(r'<(?:trkpt|rtept)[^>]*lon="([-\d.]+)"[^>]*lat="([-\d.]+)"', seg)]
            if pts:
                lines.append([(float(lo), float(la)) for la, lo in pts])
    else:
        for c in _re.findall(r"<LineString>.*?<coordinates>(.*?)</coordinates>", txt, _re.S):
            pts = [tuple(map(float, t.split(",")[:2])) for t in c.split()]
            if len(pts) > 1:
                lines.append(pts)
    return lines


def _proj(line, la0):
    k = math.cos(math.radians(la0))
    xy = [(lo * 111320 * k, la * 111320) for lo, la in line]
    cum = [0.0]
    for i in range(1, len(xy)):
        cum.append(cum[-1] + math.dist(xy[i - 1], xy[i]))
    return xy, cum


def _locate(xy, cum, x, y):
    best = (1e18, 0.0, 0, 0.0)
    for i in range(len(xy) - 1):
        (ax, ay), (bx, by) = xy[i], xy[i + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        d = math.hypot(ax + t * dx - x, ay + t * dy - y)
        if d < best[0]:
            best = (d, cum[i] + t * (cum[i + 1] - cum[i]), i, t)
    return best


def user_traces(data):
    if not os.path.isdir(TRACES):
        return
    R, PAT, Q, SH = data["R"], data["PAT"], data["Q"], data["SH"]
    by_name = {}
    for f in sorted(os.listdir(TRACES)):
        stem, ext = os.path.splitext(f)
        if ext.lower() in (".kml", ".gpx", ".geojson", ".json"):
            by_name.setdefault(stem.strip().upper(), []).extend(read_trace(os.path.join(TRACES, f)))
    used = 0
    for p in PAT:
        lines = by_name.get(R[p[0]]["s"].upper())
        if not lines:
            continue
        stops = [(Q[q][2], Q[q][1]) for q in p[4]]
        la0 = stops[0][1]
        best = None
        for line in lines:
            for cand in (line, line[::-1]):
                xy, cum = _proj(cand, la0)
                k = math.cos(math.radians(la0))
                locs = [_locate(xy, cum, lo * 111320 * k, la * 111320) for lo, la in stops]
                # arrêts au bout hors du tracé (ex. course vers le dépôt) : reliés en ligne droite
                i0, i1 = 0, len(locs) - 1
                while i0 < i1 and locs[i0][0] > TRACE_MAX:
                    i0 += 1
                while i1 > i0 and locs[i1][0] > TRACE_MAX:
                    i1 -= 1
                if i1 - i0 < 1 or i0 + (len(locs) - 1 - i1) > 2 or max(l[0] for l in locs[i0:i1 + 1]) > TRACE_MAX:
                    continue
                if any(locs[i + 1][1] < locs[i][1] - 15 for i in range(i0, i1)):
                    continue
                score = sum(l[0] for l in locs[i0:i1 + 1]) + 1000 * (i0 + len(locs) - 1 - i1)
                if best is None or score < best[0]:
                    best = (score, cand, locs, i0, i1)
        if best is None:
            print("tracé", R[p[0]]["s"], "→", p[2], ": arrêts trop loin du tracé, gardé tel quel")
            continue
        _, cand, locs, i0, i1 = best
        a, b = locs[i0], locs[i1]
        pt = lambda l: (cand[l[2]][0] + l[3] * (cand[l[2] + 1][0] - cand[l[2]][0]), cand[l[2]][1] + l[3] * (cand[l[2] + 1][1] - cand[l[2]][1]))
        pts = stops[:i0] + [pt(a)] + cand[a[2] + 1:b[2] + 1] + [pt(b)] + stops[i1 + 1:]
        flat, x0, y0 = [], 0, 0
        for lo, la in pts:
            x, y = round(lo * 1e5), round(la * 1e5)
            if flat and x == x0 and y == y0:
                continue
            flat += [x - x0, y - y0]; x0, y0 = x, y
        SH.append(flat)
        p[3] = len(SH) - 1
        used += 1
    # tracés devenus inutiles (relance du script) : on les retire
    keep = sorted({p[3] for p in PAT if p[3] >= 0})
    if len(keep) < len(SH):
        remap = {o: n for n, o in enumerate(keep)}
        data["SH"] = [SH[o] for o in keep]
        for p in PAT:
            if p[3] >= 0:
                p[3] = remap[p[3]]
    print("tracés fournis :", ", ".join(sorted(by_name)), "·", used, "parcours")


# ---------- tram : tracé réel dans le centre ----------
# Le GTFS ne donne pas de tracé pour le tram (arrêt à arrêt en ligne droite). Dans le centre, on suit les rues
# relevées par l'utilisateur (6 nov.) : Gare → rue Thiers → cours Langlet → rue de Vesle (Opéra) → Vesle.
TRAM_VIA = {
    ("Gare de Reims", "Langlet"): [(49.258393, 4.027237), (49.258251, 4.028326), (49.258150, 4.029353)],
    ("Langlet", "Opéra-Cathédrale"): [(49.254845, 4.032030)],
    ("Opéra-Cathédrale", "Vesle"): [],
}


def tram_paths(data):
    R, PAT, P, Q, SH = data["R"], data["PAT"], data["P"], data["Q"], data["SH"]
    tram = {i for i, r in enumerate(R) if r.get("m") == 1}
    name = lambda q: P[Q[q][0]][0]
    for p in PAT:
        if p[0] not in tram or p[3] >= 0:
            continue
        pts = []
        for k, q in enumerate(p[4]):
            pts.append((Q[q][1], Q[q][2]))
            if k + 1 < len(p[4]):
                a, b = name(q), name(p[4][k + 1])
                via = next((v for (x, y), v in TRAM_VIA.items() if a.startswith(x) and b.startswith(y)), None)
                if via is None:
                    via = next((v[::-1] for (x, y), v in TRAM_VIA.items() if a.startswith(y) and b.startswith(x)), [])
                pts += [w for w in via if abs(w[0] - Q[q][1]) + abs(w[1] - Q[q][2]) > 1e-6]
        flat, x0, y0 = [], 0, 0
        for la, lo in pts:
            x, y = round(lo * 1e5), round(la * 1e5)
            flat += [x - x0, y - y0]; x0, y0 = x, y
        SH.append(flat)
        p[3] = len(SH) - 1


# ---------- tronçons communs ----------
def decode_shape(flat):
    out, x, y = [], 0, 0
    for i in range(0, len(flat), 2):
        x += flat[i]; y += flat[i + 1]
        out.append((x / 1e5, y / 1e5))
    return out


def to_m(lon, lat):
    return ((lon - 4.03) * KX * M, (lat - LAT0) * M)


def from_m(x, y):
    return (x / (KX * M) + 4.03, y / M + LAT0)


def resample(pts, step):
    """Points tous les `step` mètres le long d'une polyligne (en mètres)."""
    if len(pts) < 2:
        return list(pts)
    out = [pts[0]]
    carry = 0.0
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        L = math.hypot(bx - ax, by - ay)
        d = step - carry
        while d <= L:
            f = d / L
            out.append((ax + (bx - ax) * f, ay + (by - ay) * f))
            d += step
        carry = (carry + L) % step if L > 0 else carry
    if math.hypot(out[-1][0] - pts[-1][0], out[-1][1] - pts[-1][1]) > step * 0.3:
        out.append(pts[-1])
    return out


def directions(pts):
    n = len(pts)
    out = []
    for i in range(n):
        a = pts[max(0, i - 2)]; b = pts[min(n - 1, i + 2)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        out.append((dx / L, dy / L))
    return out


class Grid:
    def __init__(self, cell):
        self.c = cell
        self.g = defaultdict(list)

    def add(self, x, y, item):
        self.g[(int(x // self.c), int(y // self.c))].append(item)

    def near(self, x, y):
        cx, cy = int(x // self.c), int(y // self.c)
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                yield from self.g.get((i, j), ())


def rdp3(pts, eps):
    """Ramer-Douglas-Peucker sur (x, y, s) : garde les indices utiles."""
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay, az = pts[a]; bx, by, bz = pts[b]
        dx, dy, dz = bx - ax, by - ay, bz - az
        L2 = dx * dx + dy * dy + dz * dz or 1e-9
        best, bi = -1, -1
        for i in range(a + 1, b):
            px, py, pz = pts[i]
            t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / L2))
            d = (ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2 + (az + t * dz - pz) ** 2
            if d > best:
                best, bi = d, i
        if best > eps * eps:
            keep[bi] = True
            stack.append((a, bi)); stack.append((bi, b))
    return [i for i, k in enumerate(keep) if k]


def trim_to_stops(pts, a, b):
    """Coupe le tracé au premier et au dernier arrêt (enlève les boucles de retournement)."""
    if len(pts) < 3:
        return pts
    d2 = lambda p, q: (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
    i0 = min(range(len(pts) // 2 + 1), key=lambda i: d2(pts[i], a))
    i1 = min(range(i0 + 1, len(pts)), key=lambda i: d2(pts[i], b))
    out = [a] + pts[i0 + 1:i1] + [b]
    return out if len(out) >= 2 else pts


RARE = 0.04   # trajets rares (scolaires, dépôt) : moins de 4 % des courses de la ligne, pas dessinés


def parallel_lines(data, step=8.0, dedupe=20.0, near=14.0, slot_m=10.0):
    R, PAT, SH, Q = data["R"], data["PAT"], data["SH"], data["Q"]
    shapes = [decode_shape(f) for f in SH]
    # polylignes par ligne, la plus fréquentée d'abord ; coupées aux arrêts de départ et d'arrivée
    per_route = defaultdict(dict)
    total = defaultdict(int)
    for p in PAT:
        r, dr, sh, stops, trs = p[0], p[1], p[3], p[4], p[5]
        total[r] += len(trs)
        key = ("s", sh, dr) if sh >= 0 else ("p", tuple(stops))
        if key not in per_route[r]:
            ll = shapes[sh] if sh >= 0 else [(Q[q][2], Q[q][1]) for q in stops]
            pts = [to_m(lo, la) for lo, la in ll]
            if sh >= 0:
                pts = trim_to_stops(pts, to_m(Q[stops[0]][2], Q[stops[0]][1]), to_m(Q[stops[-1]][2], Q[stops[-1]][1]))
            per_route[r][key] = [0, pts, dr]
        per_route[r][key][0] += len(trs)
    for r in per_route:
        for k in [k for k, v in per_route[r].items() if v[0] < RARE * total[r]]:
            del per_route[r][k]
    # sens unique : points d'une ligne que l'autre sens ne parcourt pas (à 25 m près)
    dir_grid = {}
    for r in per_route:
        dirs = {v[2] for v in per_route[r].values()}
        if len(dirs) < 2:
            continue
        for d in dirs:
            g = Grid(25.0)
            for v in per_route[r].values():
                if v[2] == d:
                    for x, y in resample(v[1], step):
                        g.add(x, y, (x, y))
            dir_grid[(r, d)] = g

    # 1) tronçons sans doublon (aller/retour, variantes) pour chaque ligne
    frags = []  # (route, [pts], sens)
    for r in sorted(per_route):
        polys = sorted(per_route[r].values(), key=lambda v: (-v[0], -len(v[1])))
        g = Grid(dedupe)
        for _, pl, dr in polys:
            s = resample(pl, step)
            if len(s) < 2:
                continue
            cov = []
            for x, y in s:
                cov.append(any((x - a) ** 2 + (y - b) ** 2 <= dedupe * dedupe for a, b in g.near(x, y)))
            i = 0
            while i < len(s):
                if cov[i]:
                    i += 1; continue
                j = i
                while j < len(s) and not cov[j]:
                    j += 1
                a, b = max(0, i - 1), min(len(s), j + 1)
                if b - a >= 10:
                    frags.append((r, s[a:b], dr))
                i = j
            for x, y in s:
                g.add(x, y, (x, y))

    # 2) pour chaque point : quelles autres lignes empruntent la même rue (même axe)
    allg = Grid(near)
    fdirs = []
    for fi, (r, pts, _) in enumerate(frags):
        ds = directions(pts)
        fdirs.append(ds)
        for i, (x, y) in enumerate(pts):
            allg.add(x, y, (r, x, y, ds[i]))
    out = []
    for fi, (r, pts, dr) in enumerate(frags):
        ds = fdirs[fi]
        raw = []
        for i, (x, y) in enumerate(pts):
            dx, dy = ds[i]
            seen = {}
            for r2, a, b, (ex, ey) in allg.near(x, y):
                if r2 == r or (a - x) ** 2 + (b - y) ** 2 > near * near:
                    continue
                c = dx * ex + dy * ey
                if abs(c) < 0.8:
                    continue
                if r2 not in seen or abs(c) > abs(seen[r2]):
                    seen[r2] = c
            group = sorted([r] + list(seen))
            n, k = len(group), group.index(r)
            lead = group[0]
            sign = 1 if lead == r else (1 if seen[lead] > 0 else -1)
            raw.append(sign * (k - (n - 1) / 2))
        # lissage : médiane (supprime les faux contacts aux carrefours) puis moyenne glissante
        n = len(raw)
        med = [sorted(raw[max(0, i - 3): i + 4])[len(raw[max(0, i - 3): i + 4]) // 2] for i in range(n)]
        sm = med
        for _ in range(2):  # deux passes : transitions douces entre faisceaux
            sm = [sum(sm[max(0, i - 6): i + 7]) / len(sm[max(0, i - 6): i + 7]) for i in range(n)]
        # sens unique : l'autre sens de la ligne ne passe pas à moins de 25 m (lissé pour ignorer les carrefours)
        og = dir_grid.get((r, 1 - dr)) if (r, 1 - dr) in dir_grid else None
        ow = [0] * n
        if og is not None:
            raw_ow = [0 if any((a - x) ** 2 + (b - y) ** 2 <= 25.0 ** 2 for a, b in og.near(x, y)) else 1 for x, y in pts]
            ow = [sorted(raw_ow[max(0, i - 4): i + 5])[len(raw_ow[max(0, i - 4): i + 5]) // 2] for i in range(n)]
        p3 = [(x, y, s * slot_m) for (x, y), s in zip(pts, sm)]
        idx = rdp3(p3, 3.0)  # tracé simplifié (le plan arrondit ensuite les angles sur un petit rayon)
        cuts = {i for i in range(1, n) if ow[i] != ow[i - 1]} | {i - 1 for i in range(1, n) if ow[i] != ow[i - 1]}
        idx = sorted(set(idx) | cuts)
        coords, slots, ows = [], [], []
        px = py = 0
        for i in idx:
            lo, la = from_m(pts[i][0], pts[i][1])
            X, Y = round(lo * 1e5), round(la * 1e5)
            coords += [X - px, Y - py]; px, py = X, Y
            slots.append(round(sm[i] * 4))
            ows.append(ow[i])
        out.append([r, coords, slots, ows] if any(ows) else [r, coords, slots])
    data["LN"] = out
    return len(frags), sum(len(o[2]) for o in out)


def finalize(data):
    split_tram(data)
    text_colors(data)
    user_traces(data)
    tram_paths(data)
    nf, npts = parallel_lines(data)
    print("tronçons du plan", nf, "points", npts)
    return data


if __name__ == "__main__":
    f = sys.argv[1]
    d = json.load(open(f, encoding="utf-8"))
    finalize(d)
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(d, fh, separators=(",", ":"), ensure_ascii=False)
