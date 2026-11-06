"""Relève les rond-points d'OpenStreetMap autour de Reims, pour simplifier leur traversée sur le plan.

Écrit build/rondpoints.json : [[lat, lon, rayon_m], ...] (centre et rayon de l'anneau).
Lancé par la tâche GitHub « Rond-points (OSM) » ; build/post.py s'en sert s'il est présent.
Données © les contributeurs d'OpenStreetMap (ODbL).
"""
import json, math, os, sys, time, urllib.parse, urllib.request

BBOX = (49.10, 3.60, 49.45, 4.45)  # sud, ouest, nord, est : tout le réseau, express compris
QUERY = f"""[out:json][timeout:120];
(
  way["junction"~"^(roundabout|circular)$"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["highway"="mini_roundabout"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom;"""
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
KX = math.cos(math.radians(49.25))
M = 111320.0


def fetch():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    last = None
    for url in SERVERS:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "HorairesGrandReims/1.0 (plan du réseau)"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:  # serveur chargé : on réessaie puis on change de serveur
                last = e
                time.sleep(10 * (attempt + 1))
    raise SystemExit(f"Overpass injoignable : {last}")


def rings(data):
    """Regroupe les morceaux d'anneau (un rond-point est parfois découpé en plusieurs voies)."""
    parts = []
    for el in data.get("elements", []):
        if el["type"] == "way" and el.get("geometry"):
            parts.append([(g["lat"], g["lon"]) for g in el["geometry"]])
    # union des morceaux qui partagent un nœud
    groups = []
    for pts in parts:
        keys = {(round(a, 7), round(b, 7)) for a, b in pts}
        hit = [g for g in groups if g["k"] & keys]
        merged = {"k": set(keys), "p": list(pts)}
        for g in hit:
            merged["k"] |= g["k"]; merged["p"] += g["p"]; groups.remove(g)
        groups.append(merged)
    out = []
    for g in groups:
        pts = list({(round(a, 7), round(b, 7)) for a, b in g["p"]})
        la = sum(p[0] for p in pts) / len(pts); lo = sum(p[1] for p in pts) / len(pts)
        r = max(math.hypot((p[1] - lo) * KX * M, (p[0] - la) * M) for p in pts)
        if 4 <= r <= 80:  # au-delà : échangeur ou grande boucle, on n'y touche pas
            out.append([round(la, 6), round(lo, 6), round(r, 1)])
    for el in data.get("elements", []):
        if el["type"] == "node":
            out.append([round(el["lat"], 6), round(el["lon"], 6), 6.0])
    return sorted(out)


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "rondpoints.json")
    res = rings(fetch())
    if len(res) < 20:
        raise SystemExit(f"Seulement {len(res)} rond-points trouvés : réponse suspecte, fichier non modifié.")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(res, f, separators=(",", ":"))
    print(len(res), "rond-points écrits dans", dest)
