"""Relève les lieux d'intérêt du Grand Reims dans OpenStreetMap, pour les chercher dans l'itinéraire.

Écoles, musées, magasins, restaurants, santé, mairies, sport, gares… avec un nom, situés dans l'une des
143 communes de la communauté urbaine du Grand Reims (contours des communes relevés au même moment).

Écrit lieux.json à la racine du site :
  { "v": "AAAA-MM-JJ", "c": [communes], "k": [[libellé, groupe]], "l": [[nom, i_libellé, i_commune, lat, lon], ...] }
Lancé par la tâche GitHub « Lieux (OSM) ». Données © les contributeurs d'OpenStreetMap (ODbL).
"""
import datetime, json, math, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "lieux.json")

# les 143 communes du Grand Reims (codes INSEE, EPCI 200067213)
INSEE = ("012 013 014 019 020 025 037 043 044 046 051 052 054 055 058 061 069 072 073 074 075 077 081 086 088 089 101 102 105 109 "
         "111 112 115 118 140 145 152 171 172 177 181 183 187 188 190 194 198 201 216 225 232 245 250 267 282 291 293 294 299 305 "
         "308 309 310 314 318 321 329 333 337 338 348 362 364 365 375 379 382 391 403 414 418 422 428 429 437 439 440 444 445 447 "
         "448 449 450 454 461 464 466 468 471 474 477 479 484 487 493 503 505 517 518 523 527 529 530 532 534 536 562 568 569 571 "
         "573 577 580 581 582 584 586 591 599 600 604 613 614 622 623 624 629 631 633 636 657 660 662").split()
BBOX = "48.95,3.45,49.60,4.65"  # sud, ouest, nord, est : tout le Grand Reims

AMENITY = {
    "school": ("École", "ens"), "kindergarten": ("École maternelle", "ens"), "college": ("Enseignement supérieur", "ens"),
    "university": ("Université", "ens"),
    "restaurant": ("Restaurant", "res"), "fast_food": ("Restauration rapide", "res"), "cafe": ("Café", "res"),
    "bar": ("Bar", "res"), "pub": ("Bar", "res"), "ice_cream": ("Glacier", "res"),
    "hospital": ("Hôpital", "san"), "clinic": ("Clinique", "san"), "pharmacy": ("Pharmacie", "san"),
    "townhall": ("Mairie", "adm"), "post_office": ("Bureau de poste", "adm"), "police": ("Police", "adm"),
    "library": ("Bibliothèque", "cul"), "theatre": ("Théâtre", "cul"), "cinema": ("Cinéma", "cul"),
    "arts_centre": ("Centre culturel", "cul"), "place_of_worship": ("Lieu de culte", "cul"),
    "marketplace": ("Marché", "com"), "community_centre": ("Salle", "adm"), "events_venue": ("Salle d'événements", "cul"),
    "conference_centre": ("Centre de congrès", "cul"),
}
SHOP = {
    "supermarket": "Supermarché", "convenience": "Supérette", "mall": "Centre commercial", "department_store": "Grand magasin",
    "bakery": "Boulangerie", "pastry": "Pâtisserie", "butcher": "Boucherie", "books": "Librairie", "clothes": "Vêtements",
    "shoes": "Chaussures", "hairdresser": "Coiffeur", "florist": "Fleuriste", "optician": "Opticien", "wine": "Cave à vins",
    "doityourself": "Bricolage", "hardware": "Bricolage", "furniture": "Ameublement", "electronics": "Électronique",
    "mobile_phone": "Téléphonie", "sports": "Sport", "toys": "Jouets", "car": "Concession auto", "car_repair": "Garage",
    "beauty": "Institut de beauté", "chocolate": "Chocolatier", "garden_centre": "Jardinerie", "jewelry": "Bijouterie",
}
TOURISM = {"museum": ("Musée", "cul"), "gallery": ("Galerie", "cul"), "attraction": ("Site touristique", "cul"),
           "zoo": ("Zoo", "loi"), "theme_park": ("Parc de loisirs", "loi"), "hotel": ("Hôtel", "loi"),
           "viewpoint": ("Point de vue", "loi")}
LEISURE = {"park": ("Parc", "spo"), "sports_centre": ("Complexe sportif", "spo"), "stadium": ("Stade", "spo"),
           "swimming_pool": ("Piscine", "spo"), "ice_rink": ("Patinoire", "spo"), "water_park": ("Parc aquatique", "spo")}
HISTORIC = {"monument": ("Monument", "cul"), "castle": ("Château", "cul"), "memorial": ("Mémorial", "cul")}

re_ = lambda d: "^(" + "|".join(d) + ")$"
QUERY = f"""[out:json][timeout:240];
rel["boundary"="administrative"]["admin_level"="8"]["ref:INSEE"~"^51({'|'.join(INSEE)})$"]({BBOX});
out geom;
(
  nwr["amenity"~"{re_(AMENITY)}"]["name"]({BBOX});
  nwr["shop"]["name"]({BBOX});
  nwr["tourism"~"{re_(TOURISM)}"]["name"]({BBOX});
  nwr["leisure"~"{re_(LEISURE)}"]["name"]({BBOX});
  nwr["historic"~"{re_(HISTORIC)}"]["name"]({BBOX});
  nwr["railway"="station"]["name"]({BBOX});
);
out tags center qt;"""
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]


def fetch():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    last = None
    for url in SERVERS:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "HorairesGrandReims/1.0 (lieux d'intérêt)"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:  # serveur chargé : on réessaie puis on change de serveur
                last = e
                print(f"{url} : {e}", file=sys.stderr)
                time.sleep(15 * (attempt + 1))
    raise SystemExit(f"Overpass injoignable : {last}")


def kind(t):
    """(libellé, groupe) d'un lieu d'après ses étiquettes OSM, ou None."""
    if t.get("access") in ("private", "no"):
        return None
    if t.get("amenity") in AMENITY:
        lab, g = AMENITY[t["amenity"]]
        if t["amenity"] == "school":
            n = t.get("name", "").lower()
            lab = "Collège" if "collège" in n or "college" in n else "Lycée" if "lycée" in n or "lycee" in n else lab
        return lab, g
    if t.get("railway") == "station":
        return "Gare", "tra"
    if t.get("tourism") in TOURISM:
        return TOURISM[t["tourism"]]
    if t.get("leisure") in LEISURE:
        return LEISURE[t["leisure"]]
    if t.get("historic") in HISTORIC:
        return HISTORIC[t["historic"]]
    if t.get("shop") and t.get("shop") not in ("vacant", "no"):
        return SHOP.get(t["shop"], "Magasin"), "com"
    return None


class Commune:
    def __init__(self, name, segs):
        self.name, self.segs = name, segs
        lats = [p for s in segs for p in (s[0], s[2])]; lons = [p for s in segs for p in (s[1], s[3])]
        self.bb = (min(lats), min(lons), max(lats), max(lons))

    def has(self, la, lo):
        if not (self.bb[0] <= la <= self.bb[2] and self.bb[1] <= lo <= self.bb[3]):
            return False
        # pair / impair sur tous les côtés des contours (extérieurs et trous) : pas besoin de refermer les anneaux
        c = False
        for a1, o1, a2, o2 in self.segs:
            if (a1 > la) != (a2 > la) and lo < o1 + (la - a1) * (o2 - o1) / (a2 - a1):
                c = not c
        return c


def main():
    data = fetch()
    communes, pois = [], []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        if el["type"] == "relation" and t.get("boundary") == "administrative" and t.get("ref:INSEE", "")[2:] in INSEE:
            segs = []
            for m in el.get("members", []):
                g = m.get("geometry") or []
                for p, q in zip(g, g[1:]):
                    segs.append((p["lat"], p["lon"], q["lat"], q["lon"]))
            if segs:
                communes.append(Commune(t.get("name", "?"), segs))
            continue
        k = kind(t)
        if not k:
            continue
        c = el.get("center") or (el if "lat" in el else None)
        if not c:
            continue
        pois.append((t["name"].strip(), k, c["lat"], c["lon"]))
    print(f"{len(communes)} communes, {len(pois)} lieux relevés", file=sys.stderr)
    if len(communes) < 130:
        raise SystemExit(f"Contours des communes incomplets ({len(communes)} / 143) : lieux.json laissé tel quel.")
    cnames = sorted({c.name for c in communes}, key=lambda s: (s != "Reims", s))
    ci = {n: i for i, n in enumerate(cnames)}
    kinds, ki, out, seen = [], {}, [], {}
    KX = math.cos(math.radians(49.25))
    for name, k, la, lo in pois:
        com = next((c for c in communes if c.has(la, lo)), None)
        if not com:
            continue  # hors du Grand Reims
        # doublons (même nom, même genre, à moins de 80 m : un magasin dessiné en point et en bâtiment)
        key = (name.lower(), k[0])
        if any(math.hypot((lo - o) * KX, la - a) * 111320 < 80 for a, o in seen.get(key, [])):
            continue
        seen.setdefault(key, []).append((la, lo))
        if k not in ki:
            ki[k] = len(kinds); kinds.append(list(k))
        out.append([name, ki[k], ci[com.name], round(la, 5), round(lo, 5)])
    out.sort(key=lambda x: (x[2], x[0].lower()))
    if len(out) < 500:
        raise SystemExit(f"Trop peu de lieux ({len(out)}) : lieux.json laissé tel quel.")
    doc = {"v": datetime.date.today().isoformat(), "src": "© les contributeurs d'OpenStreetMap (ODbL)", "c": cnames, "k": kinds, "l": out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"lieux.json : {len(out)} lieux dans {len(cnames)} communes, {os.path.getsize(OUT) // 1024} Ko", file=sys.stderr)
    by = {}
    for x in out:
        by[kinds[x[1]][0]] = by.get(kinds[x[1]][0], 0) + 1
    print(", ".join(f"{k} {v}" for k, v in sorted(by.items(), key=lambda kv: -kv[1])), file=sys.stderr)


if __name__ == "__main__":
    main()
