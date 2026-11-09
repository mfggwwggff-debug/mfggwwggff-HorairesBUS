"""Relève les feux tricolores d'OpenStreetMap autour de Reims, pour ralentir les bus du plan à leur approche.

Écrit build/feux.json : [[lat, lon], ...]. Lancé par la tâche GitHub « Feux (OSM) » ; build/make.py l'embarque
dans la page (FEUX) s'il est présent. Données © les contributeurs d'OpenStreetMap (ODbL).
"""
import json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BBOX = (49.10, 3.60, 49.45, 4.45)  # même zone que les rond-points : tout le réseau
QUERY = f"""[out:json][timeout:120];
node["highway"="traffic_signals"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
out;"""
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]


def fetch():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    last = None
    for url in SERVERS:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "HorairesGrandReims/1.0 (plan du réseau)"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:
                last = e
                time.sleep(10 * (attempt + 1))
    raise SystemExit(f"Overpass injoignable : {last}")


def main():
    pts = sorted({(round(e["lat"], 5), round(e["lon"], 5)) for e in fetch().get("elements", []) if e.get("type") == "node"})
    # un carrefour à feux = souvent 2 à 8 nœuds : on regroupe ceux à moins de ~25 m
    out = []
    for la, lo in pts:
        if not any(abs(la - a) < 0.00023 and abs(lo - o) < 0.00035 for a, o in out[-60:]):
            out.append((la, lo))
    if len(out) < 50:
        raise SystemExit(f"Trop peu de feux ({len(out)}) : feux.json laissé tel quel.")
    with open(os.path.join(HERE, "feux.json"), "w", encoding="utf-8") as f:
        json.dump([list(p) for p in out], f, separators=(",", ":"))
    print(f"feux.json : {len(out)} carrefours à feux ({len(pts)} nœuds)", file=sys.stderr)


if __name__ == "__main__":
    main()
