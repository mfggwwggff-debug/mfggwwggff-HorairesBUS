"""Convertit le tableau des correspondances (Corres.xlsx : feuilles TRAM, O1, O2) en build/corres.json.

Usage : python build/corres.py chemin/vers/Corres.xlsx [build/corres.json]

Ce que contient build/corres.json :
  { "v": 2,
    "lignes": {
      "T":  { "<arrêt>": { "quai": ..., "dirs": { "N"|"S"|"T": {...} } } },      # tram (T1 et T2)
      "O1": { "<arrêt>": { "quai": ..., "dirs": { "<direction de la O1>"|"T": {...} } } },
      "O2": { ... } } }
  - Arrêts et directions : noms des horaires.
  - Tram : N vers Neufchâtel, S vers Hôpital Debré / Gare TGV. T = terminus, positions notées dans le sens de l'ARRIVÉE (tram et BHNS, confirmé le 8 nov.).
  - BHNS : clé = direction de la O1 / O2 (« Moulin Housse », « Danemark », « C.C. Cormontreuil », « Gare Centre »).
  - "quai" : "lat" (latéraux), "dec" (latéraux décalés), "cen" (central), "uni" (quai unique).
  Chaque sens : { "portes": "d" | "g", "pos": [ ... ] } (le BHNS ouvre toujours à droite).
  Chaque élément de "pos" :
    - une ligne :   { "l": "U4", "h": "<direction des horaires>" }  (sans "h" : toutes directions)
    - un service :  { "s": "pr"|"velo"|"train"|"tgv"|"car", "n": "<libellé>" }
    - un lieu :     { "n": "<libellé>" }
    avec, selon les cas : "p" ("av"|"mi"|"ar", où descendre), "m" (mètres à pied),
    "ou" ("ici" : sur ce quai, "face" : quai d'en face, "autre" : autre quai), "nt" (précision affichée telle quelle).

Le fichier source contient des fautes de frappe et des noms qui diffèrent des horaires :
tout est ramené ici aux noms des horaires, et le script s'arrête si un nom n'est pas reconnu.
"""
import sys, os, json, re
import openpyxl

here = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "corres.json")

# Nom dans le tableau (normalisé) -> nom de l'arrêt dans les horaires
STOP = {
    "neufchatel": "Neufchâtel", "georges hebert": "Georges Hebert", "de fermat": "De Fermat",
    "jean mace": "Jean Mace", "belges": "Belges", "danton roseo": "Danton-Rauseo",
    "saint thomas": "St Thomas", "schneiter": "Schneiter", "gare centre": "Gare de Reims - Centre",
    "langlet": "Langlet", "opera-cathedrale": "Opéra-Cathédrale", "vesle": "Vesle", "comedie": "Comédie",
    "courlancy": "Courlancy", "franchet d'esperey": "Franchet d'Espèrey", "saint john perse": "Saint John Perse",
    "campus croix rouge": "Campus Crx Rouge", "kennedy": "Kennedy", "arago": "Arago",
    "mediatheque croix rouge": "Médiathèque", "hopital debre": "Hôpital Debré", "leon blum": "Léon Blum",
    "polyclinique": "Polyclinique", "gare tgv": "Gare de Champagne-Ardenne TGV",
}
# Direction dans le tableau (normalisée) -> direction dans les horaires
HEAD = {
    "neuvilette mairie": "Neuvil. Mairie", "cc cernay": "C.C. Cernay", "cc cormontreuil": "C.C. Cormontreuil",
    "cc chamfleury": "C.C. Champfleury", "gare centre": "Gare Centre", "hopital debre": "Hôpital Debré",
    "fac des sciences": "Fac des Sciences", "gare tgv": "Gare Champ. TGV", "saint brice mairie": "St Brice Mairie",
    "st brice mairie": "St Brice Mairie", "parc des expos": "Parc Expositions",
    # Le tableau dit « Croix Blanche » : c'est bien Croix du Sud (confirmé le 7 nov.).
    "croix blanche": "Croix du Sud",
    # BHNS
    "pr thillois": "P+R Thillois", "ville en tardenois": "Ville-Tardenois", "fismes": "Fismes Gare",
    "val de vesle": "Val-de-Vesle", "st symphorien": "Saint-Symphorien", "z.i. pompelle": "ZI Pompelle",
    "cc champfleury": "C.C. Champfleury",
}
# « C' » du tableau = la C des horaires (confirmé le 8 nov.).
# Arrêts de la O1 et de la O2 (nom du tableau normalisé -> nom des horaires)
STOP_BHNS = {
    "danemark": "Danemark", "baussonnet": "Baussonnet", "romains": "Romains", "gare clairmarais": "Gare Clairmarais",
    "gare centre": "Gare de Reims - Centre", "etape": "Étape", "opera": "Opéra-Cathédrale", "chanzy": "Chanzy",
    "loges coquault": "Loges Coquault", "conservatoire": "Conservatoire", "venise": "Venise", "st maurice": "St Maurice",
    "st thimotee": "St Timothee", "gouraud": "Gouraud", "crayeres": "Crayeres", "iut": "I.U.T.",
    "moulin housse": "Moulin Housse", "cc cormontreuil": "C.C. Cormontreuil", "les laps": "Les Laps",
    "alsace lorraine": "Alsace Lorraine", "picardie": "Picardie", "pheniciens": "Pheniciens", "colomb": "Colomb",
    "alexandre 1er": "Alexandre 1er", "d'orves": "D'Orves", "wilson": "Wilson", "marchandeau": "Marchandeau",
    "lycee chagall": "Lycée Chagall", "stade delaune": "Stade Delaune", "folle peine": "Folle Peine",
}
SENS_BHNS = {"moulin housse": "Moulin Housse", "danemark": "Danemark", "cc cormontreuil": "C.C. Cormontreuil",
             "gare centre": "Gare Centre", "terminus": "T"}
OU = {"sur ce quai": "ici", "quai en face": "face", "quai enface": "face", "autre quai": "autre"}
# Tram vu depuis le BHNS
TRAM_DIR = {"neufchatel": [("T1", "Neufchâtel"), ("T2", "Neufchâtel")],
            "hop debre/tgv": [("T1", "Hôpital Debré"), ("T2", "Gare Champ. TGV")], "": [("T1", None), ("T2", None)]}
SERV = {"parking relais": ("pr", "Parking Relais"), "parking velos": ("velo", "Parking vélos"),
        "gare tgv / ter": ("train", "Gare TGV et TER"), "gare ter": ("train", "Gare TER"),
        "gare champagne ardenne tgv": ("tgv", "Gare Champagne-Ardenne TGV"), "gare routiere": ("car", "Gare routière")}
QUAI = {"quai central": "cen", "quais lateraux": "lat", "quais lateraux decales": "dec", "quai lateraux": "lat",
        "quai unique": "uni"}
POS = {"avant": "av", "milieu": "mi", "arriere": "ar"}
SENS = {"neufchatel": "N", "terminus": "T", "gare tvg / hopital debre": "S", "gare tgv": "S", "hopital debre": "S"}


def norm(s):
    s = str(s).strip().lower().rstrip(".")
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("â", "a"), ("ô", "o"), ("ç", "c"), ("’", "'")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)



data = json.load(open(os.path.join(here, "data.json"), encoding="utf-8"))
heads = {}
for p in data["PAT"]:
    heads.setdefault(data["R"][p[0]]["s"], set()).add(p[2])

wb = openpyxl.load_workbook(src)
err = []


def line(n, lab, dirn):
    """Une ligne en correspondance -> élément(s) ; C' = C."""
    lab = str(lab).strip().rstrip(".")
    nt = None
    m = re.fullmatch(r"(\w+) \(arr?et (.+)\)", lab, re.I)
    if m:
        lab, nt = m.group(1), "Arrêt " + m.group(2).strip().title()
    if lab == "C'":
        lab = "C"
    h = HEAD.get(norm(dirn), str(dirn).strip()) if dirn else None
    if h and lab in heads and h not in heads[lab]:  # même nom, autre écriture (majuscules, accents)
        h = next((x for x in heads[lab] if norm(x) == norm(h)), h)
    if lab not in heads or (h and h not in heads[lab]):
        err.append(f"{n} : {lab} direction {dirn!r} introuvable (connues : {sorted(heads.get(lab, []))})")
    e = {"l": lab}
    if h:
        e["h"] = h
    if nt:
        e["nt"] = nt
    return [e]


# ---------- tram ----------
tram, cur = {}, {}
for n, r in enumerate(wb["TRAM"].iter_rows(min_row=3, values_only=True), start=3):
    r = list(r[:9])
    for i, k in ((1, "a"), (2, "t"), (3, "s")):
        if r[i]:
            cur[k] = r[i]
    if r[4]:
        cur["p"], cur["m"] = r[4], r[5]
    elif r[5] is not None:
        cur["m"] = r[5]
    stop = STOP.get(norm(cur["a"]))
    if not stop:
        err.append(f"TRAM ligne {n} : arrêt inconnu {cur['a']!r}")
        continue
    st = tram.setdefault(stop, {"quai": None, "dirs": {}})
    tq = norm(cur["t"])
    sens = SENS[norm(cur["s"])]
    if tq.startswith("quai unique"):
        st["quai"], portes = "uni", ("g" if "gauche" in tq else "d")
    else:
        st["quai"] = QUAI[tq]
        portes = "g" if st["quai"] == "cen" else "d"
    d = st["dirs"].setdefault(sens, {"portes": portes, "pos": []})
    if not r[6]:
        continue  # arrêt sans correspondance
    e = {"p": POS[norm(cur["p"])]}
    m = cur["m"]
    if isinstance(m, (int, float)):
        e["m"] = int(m)
    else:  # Campus Croix Rouge : le bus s'arrête sur le quai du tram, de l'autre côté
        e["m"] = 0
        e["nt"] = "Même quai, côté route" if "en face" not in str(m) else "Quai d'en face, côté route"
    lab = str(r[6]).strip().rstrip(".")
    if re.fullmatch(r"[A-Z]\d*", lab):
        d["pos"].append({**e, **line(f"TRAM ligne {n}", lab, r[7])[0]})
    elif norm(lab) in SERV:
        e["s"], e["n"] = SERV[norm(lab)]
        d["pos"].append(e)
    else:
        e["n"] = lab
        d["pos"].append(e)

# ---------- BHNS ----------
bhns = {}
for sheet in ("O1", "O2"):
    out = bhns.setdefault(sheet, {})
    for n, r in enumerate(wb[sheet].iter_rows(min_row=3, values_only=True), start=3):
        r = list(r[:10])
        if not r[1]:
            continue
        where = f"{sheet} ligne {n}"
        stop = STOP_BHNS.get(norm(r[1]))
        if not stop:
            err.append(f"{where} : arrêt inconnu {r[1]!r}")
            continue
        st = out.setdefault(stop, {"quai": QUAI[norm(r[2])], "dirs": {}})
        sens = SENS_BHNS[norm(r[3])]
        if sens != "T" and sens not in heads[sheet]:
            err.append(f"{where} : sens {r[3]!r} inconnu")
        d = st["dirs"].setdefault(sens, {"portes": "d", "pos": []})
        if not r[7]:
            continue  # arrêt sans correspondance
        e = {}
        if r[5] and str(r[5]).strip():
            e["p"] = POS[norm(r[5])]
        if r[6] is not None:
            e["m"] = int(r[6])
        if r[4] and str(r[4]).strip():
            e["ou"] = OU[norm(r[4])]
        lab = str(r[7]).strip()
        nl = norm(lab)
        if nl == "t1 et t2":
            for l, h in TRAM_DIR[norm(r[8] or "")]:
                d["pos"].append({**e, "l": l, **({"h": h} if h else {})})
        elif nl == "tgv et ter":
            d["pos"].append({**e, "s": "train", "n": "Gare SNCF"})
        elif re.match(r"^(?:[A-Z]\d*|C')(?: \(|$)", lab):
            d["pos"].append({**e, **line(where, lab, r[8])[0]})
        else:
            d["pos"].append({**e, "n": lab})

if err:
    sys.exit("\n".join(err))
json.dump({"v": 2, "lignes": {"T": tram, **bhns}}, open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
for k, v in {"T": tram, **bhns}.items():
    nl = sum(len(d["pos"]) for s in v.values() for d in s["dirs"].values())
    print(f"{k} : {len(v)} arrêts, {nl} éléments")
