"""Pôles en 3D (#29) : prépare les fichiers de poles/ à partir des exports de Pôle Studio.

    python build/poles.py "/chemin/POLES 3D"

Le dossier source contient JSON/<pôle>.pole.json (format pole-studio v2) et GLB/<pôle>.glb
(« Pôle Studio · compact GLB », meshopt). Pour chaque pôle :
  - poles/<id>.glb  : le décor, images recompressées (build/poles_glb.py), maillages inchangés ;
  - poles/<id>.json : seulement ce que la visionneuse utilise (origine, quais, points d'intérêt, réseau piéton) ;
puis poles/poles.json (liste) et poles/logos.json (logos des lignes, tirés de build/assets.js).
Les vignettes poles/<id>.jpg sont faites à part (capture de la visionneuse).
"""
import json, os, re, sys, glob, subprocess, unicodedata
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "poles")
src = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def r2(v): return round(v, 2) if isinstance(v, float) else v

STOP_TYPES = ("bus-pole", "tram-stop", "bhns-stop", "bus-shelter", "platform", "tram-bus-stop")
TYPE_RANK = {"bus-pole": 0, "tram-stop": 0, "bhns-stop": 0, "bus-shelter": 0, "platform": 1, "tram-bus-stop": 2}
index, lines = [], set()
AZ = {"gare-centre": 48}  # orientation de départ : comme le plan officiel du pôle (gare en haut)
for f in sorted(glob.glob(os.path.join(src, "JSON", "*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    P = d["project"]
    name = P["name"].split(" · ")[0].strip()
    pid = slug(name)
    base = os.path.basename(f).split(".pole")[0]
    glb = os.path.join(src, "GLB", base + ".glb")
    if not os.path.exists(glb):
        cand = [g for g in glob.glob(os.path.join(src, "GLB", "*.glb")) if slug(os.path.basename(g)).startswith(pid)]
        glb = cand[0] if cand else None
    nodes = {n["id"]: n for n in P["walk"]["nodes"]}
    stops, allA = {}, {}
    for o in P["objects"]:
        if o.get("type") not in STOP_TYPES or not o.get("stopId"): continue
        # un même quai peut être dessiné deux fois (abri + poteau, « · copie ») : on garde le mieux renseigné
        k = (0 if o.get("assignments") else 1, 0 if o.get("walkNode") in nodes else 1, TYPE_RANK.get(o["type"], 3))
        if o["stopId"] not in stops or k < stops[o["stopId"]][0]: stops[o["stopId"]] = (k, o)
        for a in o.get("assignments", []): allA.setdefault(o["stopId"], {})[(a["routeId"], a.get("direction"))] = a
    net = {s["id"]: s for s in d.get("network", {}).get("stops", [])}
    quais = []
    for sid, (_, o) in sorted(stops.items()):
        q = {"stopId": sid, "x": r2(o["x"]), "y": r2(o.get("y", 0)), "z": r2(o["z"]),
             "assignments": [{k: a[k] for k in ("routeId", "directionId", "direction") if k in a} for a in allA.get(sid, {}).values()],
             "walkNode": o.get("walkNode") if o.get("walkNode") in nodes else next((x.get("walkNode") for x in P["objects"] if x.get("stopId") == sid and x.get("walkNode") in nodes), None)}
        if o.get("arrivalOnly"): q["arrivalOnly"] = True
        if sid in net: q["routes"] = net[sid].get("routeIds", [])
        for a in q["assignments"]: lines.add(a["routeId"])
        for r in q.get("routes", []): lines.add(r)
        quais.append(q)
    pois = [{"id": o["id"], "label": o.get("label") or o.get("name"), "kind": o.get("kind", ""), "x": r2(o["x"]), "z": r2(o["z"]), "walkNode": o.get("walkNode")}
            for o in P["objects"] if o.get("type") == "poi" and o.get("walkNode") in nodes]
    xs, zs = [], []
    for o in P["objects"]:
        for px, pz in o.get("points", []) or []: xs.append(o.get("x", 0) + px); zs.append(o.get("z", 0) + pz)
    if not xs: xs, zs = [n["x"] for n in nodes.values()], [n["z"] for n in nodes.values()]
    out = {"id": pid, "name": name, "origin": P.get("origin"), "bounds": [r2(min(xs)), r2(min(zs)), r2(max(xs)), r2(max(zs))],
           "attribution": (P.get("provenance") or {}).get("attribution", ""),
           "quais": quais, "pois": pois,
           "walk": {"nodes": [{"id": n["id"], "x": r2(n["x"]), "y": r2(n.get("y", 0)), "z": r2(n["z"])} for n in P["walk"]["nodes"]],
                    "edges": [{k: e[k] for k in ("from", "to", "kind", "name", "accessible") if e.get(k) is not None} for e in P["walk"]["edges"]]}}
    json.dump(out, open(os.path.join(OUT, pid + ".json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    mb = None
    if glb:
        subprocess.run([sys.executable, os.path.join(ROOT, "build", "poles_glb.py"), glb, os.path.join(OUT, pid + ".glb")], check=True)
        mb = round(os.path.getsize(os.path.join(OUT, pid + ".glb")) / 1e6, 1)
    index.append({"id": pid, "name": name, "lat": (P.get("origin") or {}).get("lat"), "lon": (P.get("origin") or {}).get("lon"),
                  "stops": [q["stopId"] for q in quais], "lines": sorted({a["routeId"] for q in quais for a in q["assignments"]}),
                  "az": AZ.get(pid, 0), "glb": pid + ".glb" if glb else None, "mb": mb, "thumb": pid + ".jpg"})
    print(f"{pid}: {len(quais)} quais, {len(pois)} lieux, {len(out['walk']['nodes'])} points de marche, décor {mb} Mo")
index.sort(key=lambda p: p["name"])
json.dump({"v": 1, "poles": index}, open(os.path.join(OUT, "poles.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
txt = open(os.path.join(ROOT, "build", "assets.js"), encoding="utf-8").read()
logos = json.loads(re.search(r"const LINE_LOGOS = (\{.*?\});", txt, re.S).group(1))
json.dump({k: v for k, v in logos.items() if k in lines}, open(os.path.join(OUT, "logos.json"), "w"), separators=(",", ":"))
