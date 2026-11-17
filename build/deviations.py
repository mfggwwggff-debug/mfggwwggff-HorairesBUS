"""#74 : déviations hors GTFS, tirées de l'info trafic.

Le réseau ne met pas les petites déviations dans le GTFS (« gérées en dégradé »). L'info trafic, elle, dit
pour chaque ligne et chaque sens quel arrêt n'est plus desservi et où il est reporté (autre arrêt, ou adresse
déjà placée sur la carte par build/infotrafic.py, champ `geo`). Ce script en tire, par ligne et par sens :
  - les arrêts non desservis (bloc d'arrêts qui se suivent sur le parcours),
  - l'arrêt desservi juste avant (a) et juste après (b),
  - les arrêts provisoires (adresse, ou arrêt d'une autre ligne),
  - le tracé provisoire de a à b par les arrêts provisoires (calcul d'itinéraire routier OSRM,
    sur les rues d'OpenStreetMap ; ligne droite si le service ne répond pas),
  - le temps de parcours estimé de chaque tronçon : temps routier OSRM (calculé avec la vitesse maximale
    des rues), multiplié par un coefficient calé sur le tronçon habituel (horaire du GTFS ÷ temps OSRM du
    tracé habituel), plus un temps d'arrêt aux arrêts provisoires,
  - les journées et heures où elle s'applique.
L'appli (template.html, `devApply`) en fait des courses déviées ; la page admin/ peut corriger le tracé et
les arrêts provisoires (service d'alertes, `/extra`).

Usage : python build/deviations.py [info-trafic.json] > deviations.json
Les tracés déjà calculés (même déviation, mêmes points) sont repris de deviations.json sans rappeler OSRM.
Bibliothèque standard uniquement.
"""
import sys, os, re, json, math, unicodedata, statistics, urllib.request, datetime as dt

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
OSRM = "https://router.project-osrm.org/route/v1/driving/"
DWELL = 0.4            # min, temps d'arrêt à un arrêt provisoire
SAME_M = 80            # un arrêt « déplacé » à moins de 80 m de son quai du GTFS : déjà dans les horaires
SMALL_M = 150          # arrêts seulement décalés de quelques mètres (tous à moins de 150 m) : pas une déviation
HORIZON = 40           # jours couverts pour les infos qui reviennent (« tous les dimanches »)
TODAY = dt.date.fromisoformat(os.environ["DEV_TODAY"]) if os.environ.get("DEV_TODAY") else dt.date.today()


def key(s):
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


PETITS = {"de", "des", "du", "d", "la", "le", "les", "l", "et", "au", "aux", "a", "en", "sur", "sous", "lez", "st", "saint", "c", "cc"}


def mots(s):
    return [w for w in key(s).split() if w not in PETITS]


def dist(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    a = math.sin((lat2 - lat1) * r / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def plen(pts):  # pts = [[lon, lat], …]
    return sum(dist(a[1], a[0], b[1], b[0]) for a, b in zip(pts, pts[1:]))


# ---------- horaires ----------
D = json.load(open(os.path.join(here, "data.json"), encoding="utf-8"))
P, Q, R = D["P"], D["Q"], D["R"]
d0 = dt.date(int(D["d0"][:4]), int(D["d0"][4:6]), int(D["d0"][6:8]))


def shape(i):
    f, out, x, y = D["SH"][i], [], 0, 0
    for j in range(0, len(f), 2):
        x += f[j]; y += f[j + 1]; out.append([x / 1e5, y / 1e5])
    return out


PATS = []
for r, dr, h, sh, stops, trs in D["PAT"]:
    # heures de départ / arrivée de chaque course (minutes), comme engine.js
    times = []
    for t in trs:
        two, acc, j, A, Dp = t[1] == 1, 0, 2, [], []
        for _ in stops:
            acc += t[j]; j += 1; a = acc; dd = a
            if two: acc += t[j]; j += 1; dd = acc
            A.append(a); Dp.append(dd)
        times.append((A, Dp))
    PATS.append({"r": r, "dir": dr, "h": h, "sh": sh, "stops": stops, "names": [P[Q[q][0]][0] for q in stops], "times": times})
route_of = {x["s"]: i for i, x in enumerate(R)}


def pole_named(name, among=None):
    """Arrêt (nom du GTFS) pour un nom cité dans l'info : exact, puis mot à mot (un seul candidat)."""
    k = key(name)
    cands = among if among is not None else {P[i][0] for i in range(len(P))}
    for n in cands:
        if key(n) == k: return n
    want = mots(name)
    if not want: return None
    hits = [n for n in cands if all(any(h.startswith(w) or w.startswith(h) for h in mots(n)) for w in want)]
    return hits[0] if len(hits) == 1 else None


def dir_match(p, sens):
    """Le sens cité (« BLANCS MONTS », « C.C. CERNAY ») correspond-il à ce parcours (destination ou dernier arrêt) ?"""
    if sens is None: return True
    w = mots(sens)
    if not w: return True
    for cand in (p["h"], p["names"][-1]):
        have = mots(cand)
        if all(any(h.startswith(x) or x.startswith(h) for h in have) for x in w): return True
    return False


# ---------- lecture de l'info ----------
RX = re.compile(r"l'arr[eê]t (.+?) dans (?:le sens (.+?)|les deux sens) (?:est|sont) (report|d[ée]plac)\w*\s*(.*)$", re.I)


def entries(x):
    st = {key(a): b for a, b in (x.get("st") or []) if b}
    for b in x.get("b") or []:
        if not b.get("l"): continue
        t = "".join(r[0] for r in b.get("r") or []).strip()
        m = RX.match(t)
        if not m: continue
        stop, sens, kind, rest = m.group(1).strip(), m.group(2), m.group(3).lower(), m.group(4).strip()
        e = {"lines": [s.strip() for s in b["l"].split(",")], "stop": st.get(key(stop)) or stop, "raw": stop, "sens": sens.strip() if sens else None}
        if kind.startswith("report"):
            m2 = re.match(r"(?:à|a|au|vers)\s+l'arr[eê]t\s+(.+?)(?:\s+de la ligne\s+(\w+)(?:\s+vers\s+(.+))?)?\s*$", rest, re.I)
            if not m2: continue
            nm = re.sub(r"\s+du (dimanche|samedi).*$", "", m2.group(1)).strip()
            e["to"] = {"stop": st.get(key(nm)) or st.get(key("arrêt " + nm)) or nm, "line": m2.group(2), "vers": (m2.group(3) or "").strip() or None}
        else:
            if not b.get("geo"): continue  # « déplacé 100 mètres avant » : même arrêt, à deux pas
            g = b["geo"]
            anc = re.search(r"\((?:ancien|ex)\s+arr[eê]t\s+([^)]+?)(?:\s+de la ligne.*)?\)", rest, re.I)
            e["geo"] = {"lat": g["lat"], "lon": g["lon"], "a": g.get("a") or rest, "n": anc.group(1).strip() if anc else None}
        yield e


def when(x):
    """Journées (iso) et fenêtre horaire (minutes) de l'info ; None si on ne sait pas quand."""
    txt = key(" ".join([x.get("t") or "", x.get("p") or ""]))
    fr = re.search(r"(?:a partir de|des|apres) (\d{1,2}) ?h ?(\d{2})?", txt)
    to = re.search(r"(?:jusqu ?(?:a|au|e)?|avant) (\d{1,2}) ?h ?(\d{2})?", txt)
    w = {"from": int(fr.group(1)) * 60 + int(fr.group(2) or 0) if fr else None,
         "to": int(to.group(1)) * 60 + int(to.group(2) or 0) if to else None}
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    rec = re.search(r"(?:tous les|chaque) (lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)s?", txt)
    if x.get("start"):
        a = dt.date.fromisoformat(x["start"]); b = dt.date.fromisoformat(x["end"]) if x.get("end") else a + dt.timedelta(days=HORIZON)
        days = [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]
        if rec: days = [d for d in days if d.weekday() == jours.index(rec.group(1))]
    elif rec:
        days = [TODAY + dt.timedelta(days=i) for i in range(HORIZON) if (TODAY + dt.timedelta(days=i)).weekday() == jours.index(rec.group(1))]
    else:
        return None
    days = [d for d in days if d >= TODAY - dt.timedelta(days=1) and d <= TODAY + dt.timedelta(days=HORIZON)]
    if not days: return None
    w["days"] = [d.isoformat() for d in days]
    # dernière journée annoncée (au-delà des 40 jours couverts) : pour « reprise le … » ; None si pas de fin connue
    w["end"] = x.get("end") if x.get("start") else None
    return w


# ---------- tracé et temps ----------
OSRM_OK = True


def osrm(pts):
    """[[lon, lat], …] → (géométrie, [durée par tronçon en min], [longueur par tronçon en m]) ou None."""
    global OSRM_OK
    if not OSRM_OK: return None
    url = OSRM + ";".join(f"{lo:.6f},{la:.6f}" for lo, la in pts) + "?overview=full&geometries=geojson&continue_straight=true"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "horaires-grand-reims (github.com/mfggwwggff-debug/mfggwwggff-HorairesBUS)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.load(r)
        if j.get("code") != "Ok": return None
        rt = j["routes"][0]
        return rt["geometry"]["coordinates"], [l["duration"] / 60 for l in rt["legs"]], [l["distance"] for l in rt["legs"]]
    except Exception as e:
        print("OSRM indisponible :", e, file=sys.stderr)
        OSRM_OK = False
        return None


def straight(pts):
    ds = [dist(a[1], a[0], b[1], b[0]) * 1.3 for a, b in zip(pts, pts[1:])]
    return [list(p) for p in pts], [d / 1000 / 22 * 60 for d in ds], ds  # 22 km/h en ville


def qpt(q): return [Q[q][2], Q[q][1]]


# ---------- assemblage ----------
def build(items, old):
    cache = {d["ck"]: d for d in old if d.get("ck") and d.get("src") == "auto"}
    out, seen = [], set()
    for x in items:
        c = x.get("c") or {}
        if c.get("cond") or c.get("nat") == "info": continue  # « seulement en cas de congestion », simples infos
        # « Report de l'arrêt … » : arrêt décalé de quelques mètres, le bus garde son trajet ; l'info trafic suffit (16 nov.)
        if re.match(r"^reports? (?:de |des |du )?(?:l |la |le |les )?arrets?\b", key(x.get("t"))): continue
        w = when(x)
        if not w: continue
        es = list(entries(x))
        if not es: continue
        # par ligne et par parcours : arrêts touchés
        for line in sorted({l for e in es for l in e["lines"]}):
            if line not in route_of: continue
            ri = route_of[line]
            pats = [p for p in PATS if p["r"] == ri]
            for dr in sorted({p["dir"] for p in pats}):
                dp = [p for p in pats if p["dir"] == dr]
                main = max(dp, key=lambda p: len(p["times"]))
                mine = [e for e in es if line in e["lines"] and dir_match(main, e["sens"])]
                # un seul sens cité pour cet arrêt alors que la ligne a deux sens : dir_match l'a déjà trié
                if not mine: continue
                names = set(main["names"])
                touched = {}
                for e in mine:
                    n = pole_named(e["stop"], names)
                    if n is None: continue
                    idx = main["names"].index(n)
                    if "geo" in e:
                        g = e["geo"]
                        # déjà dans le GTFS ? (quai à moins de 80 m de la nouvelle adresse)
                        q = main["stops"][idx]
                        if dist(Q[q][1], Q[q][2], g["lat"], g["lon"]) < SAME_M: continue
                        touched[idx] = {"n": n, "geo": g}
                    else:
                        tn = pole_named(e["to"]["stop"]) or e["to"]["stop"]
                        if tn == n:  # « reporté à l'arrêt X de la ligne Y » : même arrêt, quai d'une autre ligne
                            q = rep_quai(main, idx, e["to"], tn)
                            if q is None or dist(Q[q][1], Q[q][2], Q[main["stops"][idx]][1], Q[main["stops"][idx]][2]) < SAME_M: continue
                        touched[idx] = {"n": n, "to": e["to"]}
                if not touched: continue
                # tous les arrêts touchés sont seulement décalés (à moins de 150 m) : pas une déviation
                def moved(i):
                    t, q = touched[i], Q[main["stops"][i]]
                    if "geo" in t: return dist(q[1], q[2], t["geo"]["lat"], t["geo"]["lon"])
                    tn = pole_named(t["to"]["stop"]) or t["to"]["stop"]; qq = rep_quai(main, i, t["to"], tn)
                    return dist(q[1], q[2], Q[qq][1], Q[qq][2]) if qq is not None else 1e9
                if all(moved(i) <= SMALL_M for i in touched): continue
                idxs = sorted(touched)
                # blocs d'arrêts qui se suivent
                blocks, cur = [], [idxs[0]]
                for i in idxs[1:]:
                    if i == cur[-1] + 1: cur.append(i)
                    else: blocks.append(cur); cur = [i]
                blocks.append(cur)
                for bl in blocks:
                    d = make_dev(x, w, line, main, bl, touched, cache)
                    if d and d["id"] not in seen: seen.add(d["id"]); out.append(d)
    return out


def rep_quai(p, i, to, tn):
    """Quai de l'arrêt de report : celui servi par la ligne citée (et sa direction), sinon le plus proche."""
    pi = next((k for k in range(len(P)) if P[k][0] == tn), None)
    if pi is None: return None
    qs, ref = P[pi][3], Q[p["stops"][i]]
    if to.get("line") and to["line"] in route_of:
        served = [q for pp in PATS if pp["r"] == route_of[to["line"]] and (not to.get("vers") or dir_match(pp, to["vers"])) for q in pp["stops"] if q in qs]
        if served: qs = served
    return min(qs, key=lambda q: dist(Q[q][1], Q[q][2], ref[1], ref[2]))


def make_dev(x, w, line, p, bl, touched, cache):
    names, n0, n1 = p["names"], bl[0], bl[-1]
    ia = n0 - 1 if n0 > 0 else None
    ib = n1 + 1 if n1 + 1 < len(names) else None
    prov, skip = [], []
    for i in bl:
        t = touched[i]
        if "geo" in t:
            g = t["geo"]
            same = next((v for v in prov if "lat" in v and dist(v["lat"], v["lon"], g["lat"], g["lon"]) < 40), None)
            if same:
                if t["n"] not in same["from"]: same["from"].append(t["n"])
            else:
                prov.append({"n": g["n"], "lat": g["lat"], "lon": g["lon"], "a": g["a"], "from": [t["n"]]})
            skip.append({"n": t["n"], "rep": None})
        else:
            to = t["to"]; tn = pole_named(to["stop"]) or to["stop"]
            skip.append({"n": t["n"], "rep": tn})
            if ib is not None and key(tn) == key(names[ib]): continue      # reporté à l'arrêt desservi juste après
            if ia is not None and key(tn) == key(names[ia]): continue      # … ou juste avant
            if any(v.get("pole") == tn for v in prov): continue
            q = rep_quai(p, i, to, tn)
            if q is None: continue
            prov.append({"n": tn, "pole": tn, "lat": Q[q][1], "lon": Q[q][2], "from": [t["n"]]})
    for v in prov:
        if not v["n"]: v["n"] = " / ".join(v["from"])
        v["n"] = v["n"][:1].upper() + v["n"][1:] if v["n"].isupper() is False else v["n"].title()
    # arrêts reportés vers l'arrêt desservi juste après / avant
    for s in skip:
        if s["rep"] is None:
            v = next((v for v in prov if s["n"] in v["from"]), None)
            s["rep"] = v["n"] if v else None
    # ordre des arrêts provisoires : le long du parcours habituel
    if prov:
        ref = [qpt(q) for q in p["stops"][(ia or 0):(ib + 1 if ib is not None else len(names))]]
        def along(v):
            best, acc, bd = 0, 0, 1e18
            for a, b in zip(ref, ref[1:]):
                L = dist(a[1], a[0], b[1], b[0]) or 1
                for f in (0, .25, .5, .75, 1):
                    dd = dist(a[1] + (b[1] - a[1]) * f, a[0] + (b[0] - a[0]) * f, v["lat"], v["lon"])
                    if dd < bd: bd, best = dd, acc + L * f
                acc += L
            return best
        prov.sort(key=along)
    if not prov and (ia is None or ib is None): return None
    pts = ([qpt(p["stops"][ia])] if ia is not None else []) + [[v["lon"], v["lat"]] for v in prov] + ([qpt(p["stops"][ib])] if ib is not None else [])
    did = f'{x["id"]}:{line}:{p["dir"]}:{names[n0]}'
    ck = json.dumps([did, pts, w], sort_keys=True)
    d = {"id": did, "info": x["id"], "t": x.get("t") or "", "r": line, "dir": p["dir"], "h": p["h"],
         "a": names[ia] if ia is not None else None, "b": names[ib] if ib is not None else None,
         "skip": skip, "prov": [{k: v for k, v in pv.items() if k != "from"} for pv in prov],
         "days": w["days"], "end": w.get("end"), "from": w["from"], "to": w["to"], "src": "auto", "ck": ck}
    if ck in cache and (cache[ck].get("osrm") or not OSRM_OK):
        for k in ("path", "legs", "legd", "coef", "osrm"): d[k] = cache[ck][k]
        return d
    # tracé provisoire et temps
    dev = osrm(pts) if len(pts) >= 2 else None
    d["osrm"] = bool(dev)
    if not dev: dev = straight(pts)
    geom, durs, lens = dev
    # coefficient : horaire du tronçon habituel ÷ temps routier du même tronçon
    coef = 1.6
    if ia is not None and ib is not None:
        tt = [A[ib] - Dp[ia] for A, Dp in p["times"] if A[ib] - Dp[ia] > 0]
        if tt:
            sched = statistics.median(tt)
            orig = [qpt(q) for q in p["stops"][ia:ib + 1]]
            o = osrm(orig) if d["osrm"] else None
            o_min = sum(o[1]) if o else sum(straight(orig)[1])
            if o_min > 0.2: coef = max(1.0, min(3.0, (sched - DWELL * (ib - ia - 1)) / o_min))
    d["coef"] = round(coef, 2)
    d["legs"] = [round(t * coef + (DWELL if i < len(durs) - 1 or ib is None else 0), 2) for i, t in enumerate(durs)]
    d["legd"] = [round(l) for l in lens]
    d["path"] = [[round(lo, 5), round(la, 5)] for lo, la in geom]
    return d


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "info-trafic.json")
    items = json.load(open(src, encoding="utf-8")).get("items", [])
    try: old = json.load(open(os.path.join(root, "deviations.json"), encoding="utf-8")).get("devs", [])
    except Exception: old = []
    devs = build(items, old)
    json.dump({"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "gtfs": D["feed"].get("version"), "devs": devs},
              sys.stdout, ensure_ascii=False, separators=(",", ":"))
    print(file=sys.stdout)
