"""Dernières transformations des données compactes, appelées par prep.py (et réutilisables seules) :

1. sépare la ligne « TRAM » du GTFS en deux lignes T1 (Hôpital Debré) et T2 (Gare Champagne TGV) ;
2. corrige la couleur du texte des pastilles claires (U2, U23, U24, U25, E2 : texte noir) ;
3. calcule le dessin « en parallèle » des tronçons communs : pour chaque ligne, des tronçons de tracé
   (sans doublon aller/retour) et, en chaque point, une place dans le faisceau (« slot »). Le plan décale
   chaque ligne de slot × écartement, perpendiculairement à son tracé, pour que les lignes qui partagent
   une rue soient côte à côte au lieu de se superposer. Pour un plan lisible :
   - les rond-points (build/rondpoints.json, OpenStreetMap) sont traversés tout droit, par leur centre ;
   - au terminus, la ligne s'arrête à l'arrêt : la boucle de retournement du départ n'est pas dessinée ;
   - un aller-retour dans une impasse (« piston ») et les deux sens à moins de 45 m font un seul trait ;
   - les courses directes sans arrêt intermédiaire (U25 Clovis ⇄ ZI Pompelle) ne sont pas dessinées.

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


# ---------- rond-points : traversée tout droit ----------
# build/rondpoints.json (relevé OpenStreetMap, tâche « Rond-points (OSM) ») : [[lat, lon, rayon_m], ...].
# Dans un rond-point, chaque ligne suit sa propre portion d'anneau et le dessin devient illisible.
# Comme sur le plan officiel, on fait passer chaque ligne par le centre : entrée → centre → sortie.
# Places giratoires qu'OpenStreetMap ne marque pas comme rond-points (repérées sur le plan) : [lat, lon, rayon_m]
EXTRA_RB = [
    [49.241152, 4.044684, 34.0],  # Cimetière du Sud (place Aristide Briand / avenue de Champagne)
]


def load_roundabouts():
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rondpoints.json")
    try:
        raw = json.load(open(f, encoding="utf-8"))
    except (OSError, ValueError):
        raw = []
    return [(*to_m(lo, la), r) for la, lo, r in raw + EXTRA_RB]


def _wrap(a):
    while a > math.pi: a -= 2 * math.pi
    while a < -math.pi: a += 2 * math.pi
    return a


def through_roundabouts(pts, rbg, margin=7.0):
    if not rbg or len(pts) < 2:
        return pts
    s = resample(pts, 3.0)
    near = {}
    for x, y in s:
        for rb in rbg.near(x, y):
            near[rb] = 1
    if not near:
        return pts
    for cx, cy, r in near:
        R2 = (r + margin) ** 2
        inside = [(x - cx) ** 2 + (y - cy) ** 2 <= R2 for x, y in s]
        # une courte sortie de l'anneau (bretelle, anneau mal centré) compte comme dedans : un seul passage
        k = 0
        while k < len(inside):
            if inside[k]:
                k += 1; continue
            m = k
            while m < len(inside) and not inside[m]:
                m += 1
            if 0 < k and m < len(inside) and (m - k) * 3.0 <= 45:
                for t in range(k, m):
                    inside[t] = True
            k = m
        out, i, n = [], 0, len(s)
        while i < n:
            if not inside[i]:
                out.append(s[i]); i += 1; continue
            j = i
            while j < n and inside[j]:
                j += 1
            run = s[i:j]
            # angle balayé autour du centre : une rue qui frôle l'anneau n'est pas déviée
            sweep = abs(sum(_wrap(math.atan2(b[1] - cy, b[0] - cx) - math.atan2(a[1] - cy, a[0] - cx)) for a, b in zip(run, run[1:])))
            if sweep < math.radians(35) and i > 0 and j < n:
                out += run
            else:
                if i == 0:
                    out.append(run[0])
                out.append((cx, cy))
                if j == n:
                    out.append(run[-1])
            i = j
        s = out
    return s


def despike(pts, cos_max=-0.5):
    """Retire les demi-tours brusques (pointe d'un aller-retour, raccord mal orienté) : le plan arrondit
    les angles, et un demi-tour y dessinerait une longue pointe."""
    pts = list(pts)
    changed = True
    while changed and len(pts) > 2:
        changed = False
        for k in range(1, len(pts) - 1):
            ax, ay = pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]
            bx, by = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
            la, lb = math.hypot(ax, ay), math.hypot(bx, by)
            if la < 1e-6 or lb < 1e-6 or (ax * bx + ay * by) / (la * lb) < cos_max:
                del pts[k]
                changed = True
                break
    return pts


# ---------- terminus : pas de boucle de retournement ----------
def path_len(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def trim_departure_loop(dep, stops_xy, arrivals, step=4.0, merge=25.0):
    """Départ d'un terminus : la ligne s'arrête au terminus (tracé d'arrivée) ; le début du tracé de départ,
    qui fait le tour pour repartir, n'est dessiné qu'à partir du point où il rejoint le tracé d'arrivée
    (ou de son 2e arrêt s'il le dessert avant). Rien n'est coupé si ce n'est pas une boucle courte."""
    s = resample(dep, step)
    if len(s) < 4 or not arrivals:
        return dep
    g = Grid(merge)
    for a in arrivals:
        ra = resample(a, step)
        L, acc = path_len(ra), 0.0
        for k, (x, y) in enumerate(ra):
            if k:
                acc += math.hypot(x - ra[k - 1][0], y - ra[k - 1][1])
            if L - acc > 40:  # sans les 40 derniers mètres (l'arrivée au terminus elle-même)
                g.add(x, y, (x, y))
    # 2e arrêt desservi
    sx, sy = stops_xy[1]
    i_s1 = min(range(len(s)), key=lambda i: (s[i][0] - sx) ** 2 + (s[i][1] - sy) ** 2)
    acc, cut = 0.0, None
    for i in range(1, len(s)):
        acc += math.hypot(s[i][0] - s[i - 1][0], s[i][1] - s[i - 1][1])
        if i >= i_s1:
            cut = i_s1; break
        if acc >= 40 and any((a - s[i][0]) ** 2 + (b - s[i][1]) ** 2 <= merge * merge for a, b in g.near(*s[i])):
            cut = i; break
    if not cut:
        return dep
    straight = math.hypot(s[cut][0] - s[0][0], s[cut][1] - s[0][1])
    if straight > 300 or acc < 1.4 * max(straight, 1.0):
        return dep
    # raccord au tracé d'arrivée (point le plus proche), pour que le départ parte bien de la ligne
    x, y = s[cut]
    cand = [(a, b) for a, b in g.near(x, y)]
    if cand:
        q = min(cand, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2)
        if (q[0] - x) ** 2 + (q[1] - y) ** 2 <= (2 * merge) ** 2:
            return despike([q] + s[cut:])
    return s[cut:]


def parallel_lines(data, step=8.0, dedupe=45.0, near=14.0, slot_m=10.0, oneway=50.0):
    R, PAT, SH, Q = data["R"], data["PAT"], data["SH"], data["Q"]
    shapes = [decode_shape(f) for f in SH]
    # polylignes par ligne, la plus fréquentée d'abord ; coupées aux arrêts de départ et d'arrivée
    per_route = defaultdict(dict)
    total = defaultdict(int)
    longest = defaultdict(int)
    for p in PAT:
        longest[p[0]] = max(longest[p[0]], len(p[4]))
    rbs = load_roundabouts()
    rbg = Grid(60.0)
    for rb in rbs:
        rbg.add(rb[0], rb[1], rb)
    xy = lambda q: to_m(Q[q][2], Q[q][1])
    for p in PAT:
        r, dr, sh, stops, trs = p[0], p[1], p[3], p[4], p[5]
        total[r] += len(trs)
        # courses directes sans arrêt intermédiaire (U25 Clovis ⇄ ZI Pompelle) : autre itinéraire, pas dessiné
        if len(stops) <= 2 < longest[r]:
            continue
        key = ("s", sh, dr) if sh >= 0 else ("p", tuple(stops))
        if key not in per_route[r]:
            ll = shapes[sh] if sh >= 0 else [(Q[q][2], Q[q][1]) for q in stops]
            pts = [to_m(lo, la) for lo, la in ll]
            if sh >= 0:
                pts = trim_to_stops(pts, xy(stops[0]), xy(stops[-1]))
            if r < len(R) and R[r].get("m") != 1:
                pts = through_roundabouts(pts, rbg)
            per_route[r][key] = [0, pts, dr, [xy(q) for q in stops], stops[0], stops[-1]]
        per_route[r][key][0] += len(trs)
    for r in per_route:
        for k in [k for k, v in per_route[r].items() if v[0] < RARE * total[r]]:
            del per_route[r][k]
    # terminus : le départ ne montre pas la boucle de retournement
    stop_of = lambda q: Q[q][0]
    for r in per_route:
        vals = list(per_route[r].values())
        for v in vals:
            arr = [w[1] for w in vals if w is not v and stop_of(w[5]) == stop_of(v[4])]
            if arr and len(v[3]) >= 2:
                v[1] = trim_departure_loop(v[1], v[3], arr)
    # sens unique : points d'une ligne que l'autre sens ne parcourt pas (à 50 m près : au-delà de l'écart
    # où les deux sens sont fusionnés en un seul trait)
    dir_grid = {}
    for r in per_route:
        dirs = {v[2] for v in per_route[r].values()}
        if len(dirs) < 2:
            continue
        for d in dirs:
            g = Grid(oneway)
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
        for _, pl, dr, *_ in polys:
            s = resample(pl, step)
            if len(s) < 2:
                continue
            cov = []
            for x, y in s:
                # les 50 premiers et derniers mètres d'un autre tracé ne couvrent pas : au terminus, l'arrivée
                # et le départ se touchent à l'arrêt sans suivre la même rue
                cov.append(any(not e and (x - a) ** 2 + (y - b) ** 2 <= dedupe * dedupe for a, b, e in g.near(x, y)))
            # aller-retour dans la même course (cul-de-sac, « piston ») : le retour, en sens inverse
            # sur la même rue, n'est pas redessiné : un seul trait jusqu'au bout
            ds, sg, lag = directions(s), Grid(dedupe), 2
            for i, (x, y) in enumerate(s):
                if i >= lag:
                    k = i - lag
                    sg.add(s[k][0], s[k][1], (s[k][0], s[k][1], ds[k]))
                if not cov[i]:
                    cov[i] = any((x - a) ** 2 + (y - b) ** 2 <= dedupe * dedupe and ds[i][0] * e[0] + ds[i][1] * e[1] < -0.7
                                 for a, b, e in sg.near(x, y))
            # un contact bref (croisement de rues) ne coupe pas le trait
            i = 0
            while i < len(cov):
                if not cov[i]:
                    i += 1; continue
                j = i
                while j < len(cov) and cov[j]:
                    j += 1
                if j - i < 3 and i > 0 and j < len(cov):
                    for t in range(i, j):
                        cov[t] = False
                i = j
            i = 0
            while i < len(s):
                if cov[i]:
                    i += 1; continue
                j = i
                while j < len(s) and not cov[j]:
                    j += 1
                if j - i >= 8 or ((i == 0 or j == len(s)) and j - i >= 2):  # bout de ligne : gardé même court
                    # le morceau se raccroche au trait déjà dessiné (point le plus proche), sans trou ni crochet
                    frag = s[i:j]
                    for end, at in ((0, i - 1), (1, j)):
                        if 0 <= at < len(s):
                            x, y = s[at]
                            # le trait qui a couvert ce point : autre tracé, ou retour de la même course
                            cand = [(a, b) for a, b, e in g.near(x, y) if not e] + \
                                   [(a, b) for a, b, e in sg.near(x, y) if ds[at][0] * e[0] + ds[at][1] * e[1] < -0.7]
                            # seulement un point « derrière » le morceau (au départ) ou « devant » (à la fin)
                            # sinon le trait ferait demi-tour sur lui-même
                            px, py = frag[0] if end == 0 else frag[-1]
                            dx, dy = ds[i] if end == 0 else ds[j - 1]
                            # (à 60° près de la direction du trait : le raccord se fait en biais, pas en barreau d'échelle)
                            cand = [c for c in cand if ((px - c[0]) * dx + (py - c[1]) * dy if end == 0 else (c[0] - px) * dx + (c[1] - py) * dy)
                                    >= 0.5 * math.hypot(c[0] - px, c[1] - py)]
                            if cand:
                                q = min(cand, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2)
                                frag = [q] + frag if end == 0 else frag + [q]
                            else:
                                frag = [s[at]] + frag if end == 0 else frag + [s[at]]
                    frag = despike(frag)
                    if len(frag) >= 2:
                        frags.append((r, frag, dr))
                i = j
            L, acc = path_len(s), 0.0
            for k, (x, y) in enumerate(s):
                if k:
                    acc += math.hypot(x - s[k - 1][0], y - s[k - 1][1])
                g.add(x, y, (x, y, acc < 50 or L - acc < 50))

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
        # sens unique : l'autre sens de la ligne ne passe pas à moins de 50 m (lissé pour ignorer les carrefours)
        og = dir_grid.get((r, 1 - dr)) if (r, 1 - dr) in dir_grid else None
        ow = [0] * n
        if og is not None:
            raw_ow = [0 if any((a - x) ** 2 + (b - y) ** 2 <= oneway ** 2 for a, b in og.near(x, y)) else 1 for x, y in pts]
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
