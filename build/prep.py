"""Convertit le GTFS Grand Reims Mobilités en un JSON compact pour la page."""
import sys, json, math, re, datetime as dt
from collections import defaultdict
import pandas as pd

src, out = sys.argv[1], sys.argv[2]
r = lambda f: pd.read_csv(f"{src}/{f}", dtype=str, encoding="utf-8-sig", keep_default_na=False)

stops, routes, trips, st = r("stops.txt"), r("routes.txt"), r("trips.txt"), r("stop_times.txt")
cal, cd, shapes, tr = r("calendar.txt"), r("calendar_dates.txt"), r("shapes.txt"), r("transfers.txt")
feed = r("feed_info.txt").iloc[0]

# ---------- noms ----------
SMALL = {"de", "du", "des", "la", "le", "les", "sur", "en", "aux", "et", "au"}
UP = {"TGV", "ZI", "CHU", "IUT", "P+R", "SNCF", "ESI", "INSPE", "D20", "CC"}
ACC = {"Hopital": "Hôpital", "Debre": "Debré", "Cathedrale": "Cathédrale", "Opera": "Opéra", "Republique": "République",
       "Cite": "Cité", "Faculte": "Faculté", "Ecole": "École", "Cimetiere": "Cimetière", "Lycee": "Lycée", "Remois": "Rémois",
       "Betheny": "Bétheny", "Mediatheque": "Médiathèque", "Liberte": "Liberté", "Comedie": "Comédie", "Therese": "Thérèse",
       "Leonard": "Léonard", "Leon": "Léon", "Remi": "Rémi", "Etienne": "Étienne", "Etape": "Étape", "Epinettes": "Épinettes",
       "Eluard": "Éluard", "Bleriot": "Blériot", "Neufchatel": "Neufchâtel", "Potiere": "Potière", "Sablieres": "Sablières",
       "Theatre": "Théâtre", "Betheniville": "Bétheniville", "Warmeriville": "Warmeriville", "Pere": "Père", "Genereux": "Généreux",
       "Medecine": "Médecine", "Universite": "Université", "Mendes": "Mendès", "Dostoievski": "Dostoïevski", "Eglantines": "Églantines",
       "Europe": "Europe", "Gueux": "Gueux", "Muire": "Muire", "Melies": "Méliès", "Prejean": "Préjean", "Gremillon": "Grémillon",
       "Geruzez": "Géruzez", "Coemy": "Coëmy", "Petrole": "Pétrole", "Peri": "Péri", "Saint-Remi": "Saint-Rémi", "Sebastopol": "Sébastopol"}
def nice(n):
    n = n.strip()
    letters=[c for c in n if c.isalpha()]
    if sum(c.islower() for c in letters) > len(letters) / 2:  # déjà en casse mixte
        return n
    words = re.split(r"(\s+|-|/)", n)
    res = []
    for i, w in enumerate(words):
        if not w or re.fullmatch(r"\s+|-|/", w):
            res.append(w); continue
        if w in UP or re.fullmatch(r"([A-Z]\.)+[A-Z]?\.?", w) and len(w) <= 6:
            res.append(w); continue
        lw = w.lower()
        if i > 0 and lw in SMALL:
            res.append(lw); continue
        m = re.match(r"^(d'|l')(.*)$", lw)
        if m:
            pre = m.group(1) if i > 0 else m.group(1).capitalize()
            res.append(pre + m.group(2)[:1].upper() + m.group(2)[1:]); continue
        res.append(lw[:1].upper() + lw[1:])
    s = "".join(res)
    for a, b in ACC.items():
        s = re.sub(r"(?<![\w])" + a + r"(?![\w])", b, s)
    return s

# ---------- arrêts ----------
quays = stops[stops.location_type != "1"].reset_index(drop=True)
parents = stops[stops.location_type == "1"].reset_index(drop=True)
used = set(st.stop_id.unique())
quays = quays[quays.stop_id.isin(used)].reset_index(drop=True)
# quais sans parent -> parent virtuel
pidx = {sid: i for i, sid in enumerate(parents.stop_id)}
P = [{"n": nice(row.stop_name), "lat": float(row.stop_lat), "lon": float(row.stop_lon), "q": []} for row in parents.itertuples()]
Q = []
q_ids = []
qidx = {}
for row in quays.itertuples():
    p = row.parent_station
    if p not in pidx:
        pidx[p or row.stop_id] = len(P)
        P.append({"n": nice(row.stop_name), "lat": float(row.stop_lat), "lon": float(row.stop_lon), "q": []})
        p = p or row.stop_id
    qi = len(Q)
    qidx[row.stop_id] = qi
    Q.append([pidx[p], round(float(row.stop_lat), 6), round(float(row.stop_lon), 6)])
    q_ids.append(row.stop_id)
    P[pidx[p]]["q"].append(qi)
# retirer les parents sans quai utilisé
keep = [i for i, p in enumerate(P) if p["q"]]
remap = {o: n for n, o in enumerate(keep)}
P = [P[i] for i in keep]
for q in Q: q[0] = remap[q[0]]

# ---------- calendrier ----------
start = min(cal.start_date.min(), feed.feed_start_date)
end = max(cal.end_date.max(), feed.feed_end_date)
d0 = dt.datetime.strptime(start, "%Y%m%d").date()
d1 = dt.datetime.strptime(end, "%Y%m%d").date()
ndays = (d1 - d0).days + 1
days = defaultdict(set)
DOW = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
for row in cal.itertuples():
    a = dt.datetime.strptime(row.start_date, "%Y%m%d").date()
    b = dt.datetime.strptime(row.end_date, "%Y%m%d").date()
    d = a
    while d <= b:
        if getattr(row, DOW[d.weekday()]) == "1":
            days[row.service_id].add((d - d0).days)
        d += dt.timedelta(days=1)
for row in cd.itertuples():
    k = (dt.datetime.strptime(row.date, "%Y%m%d").date() - d0).days
    if row.exception_type == "1": days[row.service_id].add(k)
    else: days[row.service_id].discard(k)
svc_ids = sorted(set(trips.service_id))
sidx = {s: i for i, s in enumerate(svc_ids)}
S = ["".join("1" if k in days[s] else "0" for k in range(ndays)) for s in svc_ids]

# ---------- lignes ----------
order = {"TRAM": 0}
def rkey(row):
    s = row.route_short_name
    m = re.match(r"([A-Z]*)(\d*)", s)
    grp = {"TRAM": 0, "U": 1, "": 1, "C": 2, "O": 3, "S": 4, "E": 5}.get(m.group(1), 6)
    return (grp, int(m.group(2) or 0), s)
routes = routes.assign(k=[rkey(x) for x in routes.itertuples()]).sort_values("k").reset_index(drop=True)
ridx = {rid: i for i, rid in enumerate(routes.route_id)}
def longname(x):
    ln = x.route_long_name
    ln = re.sub(r"^(EXPRESS \d+|[A-Z]*\d*|TRAM)\s*-\s*", "", ln)
    return " ⇄ ".join(nice(p.strip()) for p in ln.split("<>"))
R = [{"s": x.route_short_name if x.route_short_name != "20" or True else x.route_short_name,
      "id": x.route_id, "l": longname(x), "c": "#" + (x.route_color or "666666"),
      "t": "#" + (x.route_text_color or "FFFFFF"), "m": int(x.route_type)} for x in routes.itertuples()]
for x in R:
    if x["id"].startswith("U2") and x["s"].isdigit(): x["s"] = x["id"]  # « 20 » -> « U20 »

# ---------- courses / motifs ----------
def tmin(s):
    h, m, sec = s.split(":"); return int(h) * 60 + int(m) + (1 if int(sec) >= 30 else 0)
st["t_a"] = st.arrival_time.map(tmin)
st["t_d"] = st.departure_time.map(tmin)
st["seq"] = st.stop_sequence.astype(int)
st = st.sort_values(["trip_id", "seq"])
tinfo = trips.set_index("trip_id")
pat_key = {}
PAT = []
for tid, g in st.groupby("trip_id", sort=False):
    t = tinfo.loc[tid]
    seq = tuple(qidx[s] for s in g.stop_id)
    key = (t.route_id, t.direction_id, seq)
    if key not in pat_key:
        pat_key[key] = len(PAT)
        PAT.append({"r": ridx[t.route_id], "d": int(t.direction_id or 0), "s": list(seq),
                    "h": defaultdict(int), "sh": defaultdict(int), "tr": []})
    p = PAT[pat_key[key]]
    p["h"][nice(t.trip_headsign)] += 1
    p["sh"][t.shape_id] += 1
    ta, td = g.t_a.tolist(), g.t_d.tolist()
    # encodage : service, départ 1er arrêt, puis deltas (arr-dep précédent), (dep-arr) si ≠0 en négatif inutile ici
    if any(a != d for a, d in zip(ta, td)):
        times = []
        for a, d in zip(ta, td): times += [a, d]
        p["tr"].append([sidx[t.service_id], 1, times, tid])
    else:
        p["tr"].append([sidx[t.service_id], 0, ta, tid])

def enc(times):
    out = [times[0]]
    for i in range(1, len(times)): out.append(times[i] - times[i - 1])
    return out

for p in PAT:
    p["h"] = max(p["h"], key=p["h"].get)
    p["sh"] = max(p["sh"], key=p["sh"].get)
    p["tr"].sort(key=lambda x: x[2][0])
    p["ti"] = [tid for _, _, _, tid in p["tr"]]
    p["tr"] = [[sv, fl] + enc(tm) for sv, fl, tm, _ in p["tr"]]

# ---------- tracés (simplifiés) ----------
def rdp(pts, eps):
    if len(pts) < 3: return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1e-12
    dmax, idx = 0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / L
        if d > dmax: dmax, idx = d, i
    if dmax > eps:
        return rdp(pts[: idx + 1], eps)[:-1] + rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]

shapes["seq"] = shapes.shape_pt_sequence.astype(int)
shapes = shapes.sort_values(["shape_id", "seq"])
needed = {p["sh"] for p in PAT}
SH = {}
LAT0 = 49.25
kx = math.cos(math.radians(LAT0))
for sid, g in shapes[shapes.shape_id.isin(needed)].groupby("shape_id"):
    pts = [(float(lo) * kx, float(la)) for la, lo in zip(g.shape_pt_lat, g.shape_pt_lon)]
    simp = rdp(pts, 0.00004)  # ~4-5 m
    flat = []
    px = py = 0
    for x, y in simp:
        X, Y = round(x / kx * 1e5), round(y * 1e5)
        flat += [X - px, Y - py]; px, py = X, Y
    SH[sid] = flat
sh_list = sorted(SH)
shidx = {s: i for i, s in enumerate(sh_list)}
for p in PAT: p["sh"] = shidx.get(p["sh"], -1)

# ---------- correspondances à pied ----------
def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[2], b[1], b[2]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))
WALK = 70  # m/min, détour inclus via facteur 1.25
FP = defaultdict(dict)
for i, a in enumerate(Q):
    for j, b in enumerate(Q):
        if i == j: continue
        if abs(a[1] - b[1]) > 0.006 or abs(a[2] - b[2]) > 0.009: continue
        d = hav(a, b)
        same = a[0] == b[0]
        if d <= 450 or same:
            FP[i][j] = max(2 if same else 2, math.ceil(d * 1.25 / WALK) + 1)
for row in tr.itertuples():
    a, b = qidx.get(row.from_stop_id), qidx.get(row.to_stop_id)
    if a is None or b is None or a == b: continue
    d = hav(Q[a], Q[b])
    FP[a].setdefault(b, max(2, math.ceil(d * 1.25 / WALK) + 1))
FPL = [[x for kv in sorted(FP[i].items()) for x in kv] for i in range(len(Q))]

data = {
    "feed": {"name": feed.feed_publisher_name, "start": start, "end": end, "version": feed.feed_version},
    "d0": start, "nd": ndays,
    "P": [[p["n"], round(p["lat"], 6), round(p["lon"], 6), p["q"]] for p in P],
    "Q": Q, "R": R, "S": S,
    "PAT": [[p["r"], p["d"], p["h"], p["sh"], p["s"], p["tr"]] for p in PAT],
    "TI": None, "QI": [q_ids[i] for i in range(len(Q))],
    "SH": [SH[s] for s in sh_list],
    "FP": FPL,
}
# identifiants de course : numéro + suffixe factorisé
sufs, tis = [], []
for p in PAT:
    row = []
    for tid in p["ti"]:
        m = re.match(r"^(\d+)-(.*)$", tid)
        num, suf = (m.group(1), m.group(2)) if m else ("", tid)
        if suf not in sufs: sufs.append(suf)
        row.append(f"{num}.{sufs.index(suf)}")
    tis.append(" ".join(row))
data["TI"] = {"suf": sufs, "t": tis}
# tram T1/T2, couleurs de texte, tracés parallèles des tronçons communs
import post
post.finalize(data)
with open(out, "w") as f:
    json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
print("parents", len(P), "quais", len(Q), "lignes", len(R), "motifs", len(PAT), "courses",
      sum(len(p["tr"]) for p in PAT), "tracés", len(SH), "jours", ndays)
