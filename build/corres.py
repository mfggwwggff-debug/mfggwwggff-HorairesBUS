"""Convertit le tableau des correspondances (Corres.xlsx, feuille TRAM) en build/corres.json.

Usage : python build/corres.py chemin/vers/Corres.xlsx [build/corres.json]

Ce que contient build/corres.json :
  {
    "v": 1,
    "stops": {
      "<nom de l'arrêt dans les horaires>": {
        "quai": "lat" | "dec" | "cen" | "uni",   # latéraux, latéraux décalés, central, quai unique
        "dirs": {
          "N": {...},   # vers Neufchâtel
          "S": {...},   # vers Hôpital Debré / Gare TGV
          "T": {...}    # terminus : positions notées dans le sens du DÉPART
        }
      }
    }
  }
  Chaque sens : { "portes": "d" | "g", "pos": [ ... ] }
  Chaque élément de "pos" :
    - une ligne :   { "p": "av"|"mi"|"ar", "m": mètres, "l": "U4", "h": "<direction telle que dans les horaires>" }
    - un service :  { "p": ..., "m": ..., "s": "pr"|"velo"|"train"|"tgv"|"car" , "n": "<libellé>" }
    - un lieu :     { "p": ..., "m": ..., "n": "<libellé>" }
    - "nt" (facultatif) : précision affichée telle quelle.

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
}
SERV = {"parking relais": ("pr", "Parking Relais"), "parking velos": ("velo", "Parking vélos"),
        "gare tgv / ter": ("train", "Gare TGV et TER"), "gare ter": ("train", "Gare TER"),
        "gare champagne ardenne tgv": ("tgv", "Gare Champagne-Ardenne TGV"), "gare routiere": ("car", "Gare routière")}
QUAI = {"quai central": "cen", "quais lateraux": "lat", "quais lateraux decales": "dec"}
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

ws = openpyxl.load_workbook(src)["TRAM"]
out, err = {}, []
cur = {}
for n, r in enumerate(ws.iter_rows(min_row=3, values_only=True), start=3):
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
        err.append(f"ligne {n} : arrêt inconnu {cur['a']!r}")
        continue
    st = out.setdefault(stop, {"quai": None, "dirs": {}})
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
        h = HEAD.get(norm(r[7]), str(r[7]).strip())
        if lab not in heads or h not in heads[lab]:
            err.append(f"ligne {n} : {lab} direction {r[7]!r} introuvable (connues : {sorted(heads.get(lab, []))})")
        e.update(l=lab, h=h)
    elif norm(lab) in SERV:
        e["s"], e["n"] = SERV[norm(lab)]
    else:
        e["n"] = lab
    d["pos"].append(e)

if err:
    sys.exit("\n".join(err))
json.dump({"v": 1, "stops": out}, open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
nl = sum(len(d["pos"]) for s in out.values() for d in s["dirs"].values())
print(f"{os.path.relpath(dst)} : {len(out)} arrêts, {nl} correspondances")
