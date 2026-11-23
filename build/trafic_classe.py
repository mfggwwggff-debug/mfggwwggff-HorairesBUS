"""Classement des infos trafic (appelé par build/infotrafic.py, rejoué par build/test_trafic.py).

Une info répond à quatre questions séparées, et l'appli en déduit ce qu'elle affiche :
  - effets   : ce qui se passe (interruption, départs non assurés, blocage, déviation, arrêt déplacé,
               horaires perturbés, panne technique, nouveauté, fin de perturbation) ;
  - gravité  : bloquant (rouge, 3), gênant (orange, 2), déviation (jaune + pastille, 1),
               mineur (jaune sans pastille, 1), aucune (simple info) ;
  - moment   : laissé à l'appli (dates, jours cités, « tous les dimanches »), qui le recalcule chaque minute ;
               une info conditionnelle (« seulement en cas de… ») est une simple info ;
  - portée   : arrêts, ligne, lignes, réseau.

L'info est lue phrase par phrase : une phrase qui annonce une fin ou une nouveauté (« fin de report »,
« nouvelle desserte », « retour à la normale ») n'apporte pas de gêne, même si elle contient « report ».
Une info où rien n'est reconnu reste affichée, avec `sur: false`, et part dans la liste « à vérifier ».

Les arrêts cités (en gras après « L'arrêt », « à l'arrêt », ou dans « Départs de … non assurés ») sont
rapprochés des arrêts du GTFS (build/data.json), en cherchant d'abord parmi les arrêts des lignes de l'info,
avec les abréviations du réseau (« Fac des Sciences », « Parc Expositions », « Gare de Reims - Centre »…)
et une table d'équivalences à la main (build/arrets-alias.json).
"""
import re, os, json, difflib, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))


def plain(s):
    s = (s or "").replace("’", "'").replace("œ", "oe").replace("Œ", "oe").replace("\xa0", " ")
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()


# ---------------------------------------------------------------- effets
# Ordre = gravité décroissante. Chaque effet : (nom, gravité, expression).
GRAV = {"bloquant": 3, "genant": 2, "deviation": 1, "mineur": 1, "aucune": 0}
EFFETS = [
    ("interruption", "bloquant", r"interrompu|interruption|suspendue?s?\b|suspension (du trafic|de la ligne|du service|des lignes)"
        r"|ne (circule|circulent|roule|roulent|passe|passent) (plus|pas)|n'(circule|circulent|est plus assure)"
        r"|aucun (bus|tram|vehicule|service|depart)|plus aucun|trafic (arrete|stoppe|coupe|nul)|arret (total|complet) du trafic"
        r"|ligne (fermee|coupee)|service (arrete|annule|suspendu)|reseau (paralyse|bloque|a l'arret|arrete|interrompu|suspendu)"
        r"|(bus|tram|vehicules?) (sont |est )?(a l'arret|immobilises?)"),
    ("non_assure", "genant", r"non assure|pas assure|ne (sera|seront|sont|est) pas assure|supprime|annule"),
    ("blocage", "genant", r"bloque|blocage|barrage|manifestation|manif\b|rassemblement|cortege|defile\b|greve|mouvement social"
        r"|accident|incident|collision|(vehicule|bus|tram|camion) en panne|panne (d'un|du|de) (vehicule|bus|tram)|colis suspect|alerte"
        r"|intervention (des|de la|de) (secours|pompiers|police|gendarmerie|forces)|pompiers|forces de l'ordre|fige"
        r"|mal stationne|stationnement (genant|anarchique)|obstacle|chaussee (coupee|inondee|fermee|glissante)|(route|rue|voie|pont|avenue|boulevard|bld) (est )?(coupee?|fermee?|barree?)"
        r"|neutralise|inondation|innond|neige|verglas|intemperie|tempete|orage|embouteillage|bouchon|congestion"
        r"|circulation (difficile|perturbee|dense|tres chargee|bloquee|ralentie|saturee)|ralenti|retard"),
    ("horaires", "genant", r"forte perturbation|perturbation (sur|des) (les )?horaires|horaires (perturbes|modifies|non garantis)"
        r"|fortes? perturbations?|perturbations? importantes?|trafic (tres )?perturbe|ligne perturbee|perturbe"),
    ("deviation", "deviation", r"devie|deviation|itineraire (modifie|adapte)|non desservi|pas desservi|plus desservi"
        r"|ne (sera|seront|sont|est) (pas|plus) desservi|ne (dessert|desservent|desservira|desserviront) (pas|plus)"
        r"|ne peu(t|vent) (pas|plus) desservir|terminus (provisoire|reporte|limite)|limite[es]? a l'arret|en (retournement|terminus partiel)"),
    ("deplacement", "mineur", r"deplace|report|transfer|arret provisoire|decale"),
    ("technique", "aucune", r"(temps reel|kif|appli|application|site (internet|web)|bornes?|ecrans?|information voyageurs|sms|billettique"
        r"|distributeurs?|paiement|valideurs?|titres?)[^.]{0,60}(dysfonctionnement|panne|indisponible|hors service|perturbe|ne fonctionne)"
        r"|(dysfonctionnement|panne|indisponibilite)[^.]{0,40}(temps reel|kif|appli|application|site|bornes?|ecrans?|information voyageurs|billettique|valideurs?)"),
    ("nouveaute", "aucune", r"nouvel(le)?s? (arrets?|ligne|desserte|offre|service)|nouveaux (arrets|horaires)|desormais desservi"
        r"|(est|sont|seront|sera) desservis? par|mise en service|ouverture (de la|d'une) (ligne|station)|creation (d'un|de la|des)"
        r"|prolongement de la ligne|nouvel itineraire"),
    ("fin", "aucune", r"fin (de|du|des) (report|deviation|travaux|perturbation|la deviation|l'interruption|suspension)"
        r"|retour (a la normale|a l'itineraire|a la desserte|de la desserte)|reprise (du trafic|de la circulation|normale|de la desserte|du service)"
        r"|(trafic|circulation|desserte|service) (est )?(retabli|reprend|normal)|(est|sont) (de nouveau|a nouveau) (desservi|en service|assure)"
        r"|ne (sera|seront|sont|est) plus (devie|reporte|deplace)|\bleve(e|es|s)?\b"),
]
EFFETS = [(n, g, re.compile(rx)) for n, g, rx in EFFETS]
# une phrase de fin ou de nouveauté n'apporte pas de gêne
APAISE = {"fin", "nouveaute"}
CONDITION = re.compile(r"seulement en cas|uniquement en cas|en cas de (congestion|besoin|forte|neige|verglas|manifestation)|si (necessaire|besoin)|eventuellement|selon (les conditions|la circulation|l'affluence)")
RESEAU = re.compile(r"ensemble du reseau|tout le reseau|toutes (les|nos) lignes|l'ensemble des lignes|totalite du reseau|reseau (est |sera )?(interrompu|suspendu|bloque|arrete|paralyse|perturbe)"
                    r"|neige|verglas|intemperie|tempete|greve|mouvement social")
# phrases de politesse : ne disent rien
VIDE = re.compile(r"^(merci (de|pour) votre (comprehension|patience)|nous vous prions de nous excuser.*|conseil deplacement.*|nous vous invitons.*)$")


def phrases(item):
    out = [plain(item.get("t", "")), plain(item.get("p", ""))]
    for b in item.get("b") or []:
        txt = plain("".join(x[0] for x in (b.get("r") or [])))
        out += [s for s in re.split(r"(?<=[.!?])\s+", txt)]
    return [s.strip(" :;-") for s in out if s and s.strip(" :;-") and not VIDE.match(s.strip(" :;-."))]


def classe(item, nb_lignes_reseau=29):
    """Les quatre réponses pour une info (dict produit par infotrafic.parse)."""
    effets, detail = [], []
    for s in phrases(item):
        trouve = [n for n, g, rx in EFFETS if rx.search(s)]
        if "technique" in trouve:  # « temps réel en panne » : pas une panne de bus
            trouve = [n for n in trouve if n not in ("blocage", "interruption", "horaires")]
        if APAISE & set(trouve):
            # « Fin de report », « nouvelle desserte » : on garde la fin / la nouveauté, pas la gêne… sauf si la phrase
            # annonce clairement une gêne en plus (« nouvelle déviation »)
            garde = [n for n in trouve if n in APAISE]
            if re.search(r"nouvel(le)? deviation|nouvelle interruption", s): garde += ["deviation"]
            trouve = garde
        for n in trouve:
            if n not in effets: effets.append(n)
        if trouve: detail.append([s[:120], trouve])
    lignes = item.get("lines") or []
    tout = " ".join(phrases(item))
    cond = bool(CONDITION.search(tout))
    rt = bool(item.get("rt"))

    gene = [n for n in effets if n not in ("technique", "nouveaute", "fin")]
    if gene:
        grav = max((g for n, g, _ in EFFETS if n in gene), key=lambda g: GRAV[g])
        nat, sur = "perturbation", True
    elif effets:
        grav, sur = "aucune", True
        nat = "technique" if "technique" in effets else "info"
    else:
        # rien de reconnu : visible quand même, à vérifier. En temps réel, le réseau l'a mise dans son encadré
        # « en direct » : on la traite comme gênante plutôt que de la cacher.
        grav, nat, sur = ("genant", "perturbation", False) if rt else ("mineur", "perturbation", False)
    if cond and nat == "perturbation" and not rt:
        # « seulement en cas de congestion » : simple info. Quand le réseau active la déviation, il publie une info
        # en temps réel à part, classée normalement.
        grav, nat = "aucune", "info"
    if rt:
        # règle du 16 nov. : une info de l'encadré temps réel est toujours au moins une perturbation gênante,
        # et une interruption si le message en parle (gravité « bloquant », déjà donnée par l'effet).
        if grav != "bloquant": grav = "genant"
        nat, sur = "perturbation", sur or bool(effets)
    niv = GRAV[grav]
    pastille = grav in ("bloquant", "genant", "deviation")

    if "technique" in effets and not gene: portee = "aucune"   # panne du temps réel, de Kif&go… : pas tout le réseau
    elif not lignes and (RESEAU.search(tout) or (rt and gene)): portee = "reseau"
    elif len(lignes) >= max(12, nb_lignes_reseau * 0.6): portee = "reseau"
    elif len(lignes) > 1: portee = "lignes"
    elif lignes: portee = "ligne"
    else: portee = "inconnue"
    return {"effets": effets, "grav": grav, "niv": niv, "pastille": pastille, "nat": nat, "cond": cond,
            "portee": portee, "sur": sur, "pourquoi": detail[:6]}


# ---------------------------------------------------------------- arrêts
PETITS = {"de", "des", "du", "d", "la", "le", "les", "l", "et", "au", "aux", "a", "en", "sur", "sous", "lez", "arret", "arrets"}


def cle(s):
    s = plain(s)
    s = re.sub(r"\bc\.\s?c\.?|\bcentre commercial\b", "cc ", s)
    s = re.sub(r"\bsainte?s?\b", "st", s)
    s = re.sub(r"\b(bld|bvd|bd)\b", "boulevard", s)
    s = s.replace("p+r", "pr")
    return re.sub(r"[^a-z0-9.]+", " ", s).strip()


def mots(s):
    return [w for w in cle(s).replace(".", " . ").split() if w and w not in PETITS and w != "."]


def mots_abr(s):
    """Mots d'un nom du GTFS, en gardant la marque d'abréviation (« Neuvil. », « Monu. », « Crx »)."""
    out = []
    for w in re.findall(r"[a-z0-9]+\.?", cle(s)):
        if w.rstrip(".") in PETITS: continue
        out.append(w)
    return out


def mot_ok(a, g):
    """Le mot cité `a` correspond-il au mot du GTFS `g` ? 1 : même mot (abréviation, pluriel) ; 0,8 : début de mot
    ou une faute de frappe ; 0 : non."""
    abr = g.endswith("."); g = g.rstrip(".")
    if a == g: return 1
    if abr and len(g) >= 3 and a.startswith(g): return 1
    sa, sg = a.rstrip("sx"), g.rstrip("sx")
    if sa == sg and sa: return 1
    if len(a) >= 5 and g.startswith(a): return 0.9       # « expos » → « expositions »
    if len(g) >= 3 and len(a) > len(g) and a.startswith(g) and len(g) >= len(a) * 0.5: return 0.9   # « faculte » → « fac »
    if len(a) >= 5 and len(g) >= 5 and difflib.SequenceMatcher(None, a, g).ratio() >= 0.83: return 0.8
    return 0


ABR = {"crx": "croix", "fac": "faculte", "monu": "monument", "gal": "general", "ste": "st", "pl": "place", "grd": "grand",
       "ptt": "petit", "warmeri": "warmeriville", "neuvil": "neuvillette", "sculpt": "sculpteur", "h": "homme"}


class Arrets:
    def __init__(self, data=None):
        try:
            d = data or json.load(open(os.path.join(HERE, "data.json"), encoding="utf-8"))
        except Exception:
            d = {"P": [], "Q": [], "R": [], "PAT": []}
        self.noms = [p[0] for p in d["P"]]
        self.lignes = {}   # nom court de ligne → indices d'arrêts desservis
        R = d.get("R") or []
        for pat in d.get("PAT") or []:
            try:
                s = R[pat[0]]["s"]
                for q in pat[4]: self.lignes.setdefault(s, set()).add(d["Q"][q][0])
            except Exception:
                pass
        self.nb_lignes = len(R) or 29
        try:
            self.alias = {cle(k): v for k, v in json.load(open(os.path.join(HERE, "arrets-alias.json"), encoding="utf-8")).items() if not k.startswith("_")}
        except Exception:
            self.alias = {}

    def _score(self, cite, i):
        nom = self.noms[i]
        if cle(nom).replace(".", "") == cle(cite).replace(".", ""): return 1.0
        ga = [ABR.get(w.rstrip("."), w) + ("." if w.endswith(".") and w.rstrip(".") not in ABR else "") for w in mots_abr(nom)]
        ca = mots(cite)
        if not ga or not ca: return 0
        gw = [max(mot_ok(a, g) for a in ca) for g in ga]
        cw = [max(mot_ok(a, g) for g in ga) for a in ca]
        g_ok, c_ok = sum(1 for w in gw if w), sum(1 for w in cw if w)
        q = min([w for w in gw + cw if w] or [1])   # un mot seulement approché : moins sûr
        if g_ok == len(ga) and c_ok == len(ca): return 0.95 * q
        # un des deux noms couvre l'autre, avec au moins la moitié des mots de l'autre (« Gare Centre » → « Gare de Reims - Centre »)
        if g_ok == len(ga) and c_ok / len(ca) >= 0.5: return (0.6 + 0.25 * c_ok / len(ca)) * q
        if c_ok == len(ca) and g_ok / len(ga) >= 0.5: return (0.6 + 0.25 * g_ok / len(ga)) * q
        r = difflib.SequenceMatcher(None, cle(cite), cle(nom)).ratio()
        return r if r >= 0.8 else 0

    def trouve(self, cite, lignes=()):
        """Nom GTFS de l'arrêt cité, ou None. Cherche d'abord parmi les arrêts des lignes de l'info."""
        if not self.noms: return None
        c = re.sub(r"^(l')?arr[êe]ts?\s+", "", cite.strip(), flags=re.I)
        c = re.sub(r"\s+(de|du) (la )?ligne\b.*$|\s+(vers|direction)\b.*$|\s*\(.*$|\s+du dimanche.*$", "", c, flags=re.I).strip(" ,.:")
        if not c: return None
        if cle(c) in self.alias: return self.alias[cle(c)]
        pool = set()
        for l in lignes: pool |= self.lignes.get(l, set())
        for cand in ([sorted(pool)] if pool else []) + [range(len(self.noms))]:
            best = sorted(((self._score(c, i), -len(self.noms[i]), i) for i in cand), reverse=True)
            if best and best[0][0] >= 0.7:
                # deux arrêts aussi bons : on ne choisit pas au hasard
                if len(best) > 1 and best[0][0] - best[1][0] < 0.04 and best[0][0] < 1 and self.noms[best[1][2]] != self.noms[best[0][2]]:
                    continue
                return self.noms[best[0][2]]
        return None


def arrets_cites(item):
    """Noms d'arrêts cités dans l'info : gras après « L'arrêt » / « à l'arrêt », et « Départs de X non assurés »."""
    out = []
    for b in item.get("b") or []:
        r = b.get("r") or []
        for i in range(len(r)):
            if not r[i][1]: continue
            avant = plain(r[i - 1][0]) if i else ""
            if re.search(r"arr[eê]ts?\s*$", avant) or re.match(r"(?i)arr[êe]t\s", r[i][0]):
                out.append(r[i][0])
        txt = "".join(x[0] for x in r)
        for m in re.finditer(r"(?i)d[ée]parts? (?:de |du |d'|des )(.+?) (?:sont |ne sont pas )?(?:non|pas) assur", txt):
            out.append(m.group(1))
        # 23 nov. 2026 : « A l'arrêt Fac des Sciences : 7h57, 9h09… » (sans gras) sous une info « non assurés »
        m = re.match(r"(?i)\s*(?:à|a|depuis|au départ de|au depart de) l['’]?arr[êe]ts? (?:de |du |d')?([^:]+?)\s*:\s*.*\d{1,2}\s?h", txt)
        if m: out.append(m.group(1))
    seen, res = set(), []
    for n in out:
        n = n.strip()
        if n and cle(n) not in seen: seen.add(cle(n)); res.append(n)
    return res


def complete(items, arrets=None):
    """Ajoute à chaque info : `c` (classement) et `st` (arrêts cités → nom GTFS, None si introuvable)."""
    arrets = arrets or Arrets()
    for it in items:
        it["c"] = classe(it, arrets.nb_lignes)
        it["c"].pop("pourquoi", None)   # détail de lecture : seulement pour le banc d'essai
        it["st"] = [[n, arrets.trouve(n, it.get("lines") or [])] for n in arrets_cites(it)]
        if any(v is None for _, v in it["st"]): it["c"]["sur"] = False
    return items
