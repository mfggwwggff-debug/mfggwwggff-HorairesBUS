"""Relève l'info trafic publiée sur grandreims-mobilites.fr et écrit info-trafic.json.

Le site n'a pas de flux de données ouvert et bloque la lecture depuis une autre page : ce script
tourne dans GitHub Actions (toutes les 15 minutes environ) et l'appli relit le fichier produit.

Chaque info porte, si la page la donne, sa rubrique : "rt" (true = temps réel, false = par ligne).
Sans rubrique reconnue, l'appli devine : une info sans dates est traitée comme du temps réel.

Usage : python build/infotrafic.py [fichier_html_local] > info-trafic.json
Sans argument, la page est téléchargée. Bibliothèque standard uniquement.
"""
import sys, os, re, json, html, hashlib, datetime as dt, urllib.request, urllib.parse

URL = "https://www.grandreims-mobilites.fr/fr/1JA-Info-trafic.html"
BASE = "https://www.grandreims-mobilites.fr"
ALIAS = {"CITYBUS": "C", "TRAM": "T1,T2", "T": "T1,T2", "A": "T1", "B": "T2"}
MOIS = {m: i + 1 for i, m in enumerate(["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
                                         "aout", "septembre", "octobre", "novembre", "decembre"])}


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; horaires-grand-reims; +https://github.com/mfggwwggff-debug/mfggwwggff-HorairesBUS)", "Accept-Language": "fr"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text(s):
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def runs(s):
    """Texte découpé en morceaux [texte, gras] (seul le gras est gardé)."""
    s = re.sub(r"<(/?)(?:b|strong)\b[^>]*>", lambda m: "\x02" if m.group(1) else "\x01", s, flags=re.I)
    out, bold = [], 0
    for part in re.split(r"([\x01\x02])", s):
        if part == "\x01": bold = 1; continue
        if part == "\x02": bold = 0; continue
        t = text(part)
        if not t: continue
        if part[:1].isspace() and out: t = " " + t
        if part[-1:].isspace(): t += " "
        if out and out[-1][1] == bold: out[-1][0] += t
        else: out.append([t, bold])
    if out:
        out[0][0] = out[0][0].lstrip(); out[-1][0] = out[-1][0].rstrip()
    return [r for r in out if r[0]]


def plain(s):
    return s.lower().translate(str.maketrans("éèêëàâäîïôöûüç", "eeeeaaaiioouuc"))


def dates(h):
    """Dates de début et de fin trouvées dans l'intitulé (« A partir du lundi 19 octobre 2026 jusqu'au … »)."""
    p = plain(h)
    found = []
    for m in re.finditer(r"(\d{1,2})(?:er)?\s+(" + "|".join(MOIS) + r")(?:\s+(\d{4}))?", p):
        d, mo, y = int(m.group(1)), MOIS[m.group(2)], m.group(3)
        found.append((m.start(), d, mo, int(y) if y else None))
    if not found:
        return None, None
    year = next((y for _, _, _, y in found if y), dt.date.today().year)
    iso = lambda f: f"{f[3] or year:04d}-{f[2]:02d}-{f[1]:02d}"
    cut = p.find("jusqu")
    start = [f for f in found if cut < 0 or f[0] < cut]
    end = [f for f in found if cut >= 0 and f[0] > cut]
    s = iso(start[0]) if start else None
    e = iso(end[0]) if end else (s if re.match(r"\s*le\s", p) else None)
    return s, e


def sections(page):
    """Rubriques de la page (titres et blocs marqués « temps réel »), avec leur position."""
    marks = []
    for m in re.finditer(r"<h[1-4][^>]*>(.*?)</h[1-4]>", page, re.S | re.I):
        marks.append((m.start(), plain(text(m.group(1)))))
    for m in re.finditer(r'<[a-z]+[^>]*(?:id|class)="[^"]*(temps[-_ ]?reel|tempsreel|realtime|real-time|par[-_ ]?ligne)[^"]*"', page, re.I):
        marks.append((m.start(), plain(m.group(1)).replace("-", " ").replace("_", " ")))
    return sorted(marks)


def rubrique(marks, pos):
    """True : rubrique temps réel ; False : rubrique par ligne ; None : inconnu (l'appli devine)."""
    prev = [t for p, t in marks if p < pos]
    for t in reversed(prev):
        if re.search(r"temps ?reel|en direct|realtime|real time|perturbations? en cours", t): return True, t
        if re.search(r"par ?ligne|travaux|prevue|a venir", t): return False, t
    return None, ""


def parse(page):
    items = []
    marks = sections(page)
    for m in re.finditer(r'<details[^>]*data-lines="([^"]*)"[^>]*>(.*?)</details>', page, re.S | re.I):
        lines, inner = m.group(1), m.group(2)
        sm = re.search(r"<summary[^>]*>(.*?)</summary>", inner, re.S | re.I)
        if not sm: continue
        title = text(re.split(r"<div", sm.group(1), 1)[0])
        body = inner[sm.end():]
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S | re.I)
        period = text(h2.group(1)) if h2 else ""
        if h2: body = body[:h2.start()] + body[h2.end():]
        blocks = []
        # lignes de tableau : pastille de ligne + texte
        def row(mr):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", mr.group(0), re.S | re.I)
            line = ""
            for c in cells:
                im = re.search(r'<img[^>]*title="([^"]+)"', c, re.I) or re.search(r'<img[^>]*alt="([^"]+)"', c, re.I)
                if im and not text(c): line = line or im.group(1).strip(); continue
                r = runs(c)
                if r: blocks.append({"l": line, "r": r})
            return ""
        body = re.sub(r"<tr\b.*?</tr>", row, body, flags=re.S | re.I)
        body = re.sub(r"<table\b.*?</table>", "", body, flags=re.S | re.I)
        for mp in re.finditer(r"<(p|li|h3|h4)\b[^>]*>(.*?)</\1>", body, re.S | re.I):
            seg = mp.group(2)
            for a in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', seg, re.S | re.I):
                href = html.unescape(a.group(1))
                if re.search(r"\.(jpe?g|png|gif|webp|pdf)(\?|$)", href, re.I) or "<img" in a.group(2):
                    blocks.append({"img": href if href.startswith("http") else BASE + href})
            if "<img" in seg and not re.search(r"<a\b", seg, re.I):
                im = re.search(r'<img[^>]*src="([^"]+)"', seg, re.I)
                if im: blocks.append({"img": im.group(1) if im.group(1).startswith("http") else BASE + im.group(1)})
            seg = re.sub(r"<a[^>]*>\s*(https?://[^<]+)</a>", lambda a: a.group(1), seg)
            r = runs(seg)
            if r and not re.fullmatch(r"https?://\S+", "".join(x[0] for x in r)):
                blocks.append({"r": r})
        ls = []
        for tok in lines.split(","):
            tok = tok.strip().upper()
            for t in ALIAS.get(tok, tok).split(","):
                if t and t not in ls: ls.append(t)
        start, end = dates(period)
        iid = hashlib.sha1((title + "|" + period).encode()).hexdigest()[:10]
        item = {"id": iid, "t": title, "lines": ls, "p": period, "start": start, "end": end, "b": blocks}
        rt, sec = rubrique(marks, m.start())
        if rt is not None: item["rt"] = rt
        if sec: item["sec"] = sec[:60]
        items.append(item)
    return items


# ---------- arrêt reporté à une adresse : position sur le plan ----------
# « L'arrêt RETHEL … est déplacé au 179 rue de Neufchâtel » : on cherche l'adresse avec la Base Adresse
# Nationale (api-adresse.data.gouv.fr), près de l'arrêt habituel. Résultats gardés d'un relevé à l'autre.
HERE = os.path.dirname(os.path.abspath(__file__))
ADDR = re.compile(r"(?:d[ée]plac[ée]e?s?|report[ée]e?s?)\s+(?:\(.*?\)\s+)?(?:face\s+)?(?:au niveau\s+)?(?:du|au|à hauteur du)\s+"
                  r"(\d+\s*(?:bis|ter)?\s+(?:rue|avenue|av\.?|boulevard|bld|bd|place|chemin|route|all[ée]e|impasse|quai|cours|rond-point)\b[^,.;()]*)", re.I)


def norm_stop(s):
    s = plain(s)
    s = re.sub(r"\bsainte?\b", "st", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def stops_index():
    try:
        d = json.load(open(os.path.join(HERE, "data.json"), encoding="utf-8"))
        return {norm_stop(p[0]): (p[1], p[2]) for p in d["P"]}
    except Exception:
        return {}


def geocode(addr, near):
    q = {"q": addr, "limit": 1}
    if near: q.update(lat=near[0], lon=near[1])
    req = urllib.request.Request("https://api-adresse.data.gouv.fr/search/?" + urllib.parse.urlencode(q), headers={"User-Agent": "horaires-grand-reims"})
    with urllib.request.urlopen(req, timeout=10) as r:
        f = json.load(r)["features"]
    if not f or f[0]["properties"].get("score", 0) < 0.45: return None
    lon, lat = f[0]["geometry"]["coordinates"]
    if near and ((lat - near[0]) * 111) ** 2 + ((lon - near[1]) * 73) ** 2 > 2.0 ** 2:
        return None   # à plus de 2 km de l'arrêt : sans doute une autre rue du même nom
    return [round(lat, 6), round(lon, 6)]


def add_geo(items, cache):
    idx = None
    for it in items:
        for b in it["b"]:
            r = b.get("r") or []
            txt = "".join(x[0] for x in r)
            m = ADDR.search(txt)
            if not m: continue
            addr = re.sub(r"\b(bld|bd)\b\.?", "boulevard", m.group(1), flags=re.I).strip()
            stop = next((r[i][0] for i in range(1, len(r)) if r[i][1] and re.search(r"arr[êe]ts?\s*$", r[i - 1][0], re.I)), "")
            key = addr + "|" + stop
            if key not in cache:
                if idx is None: idx = stops_index()
                near = idx.get(norm_stop(stop))
                try: cache[key] = geocode(addr + " Reims" if not near else addr, near)
                except Exception: cache[key] = None
            if cache.get(key): b["geo"] = {"lat": cache[key][0], "lon": cache[key][1], "a": addr}


def old_cache():
    """Adresses déjà trouvées lors du relevé précédent (info-trafic.json à la racine)."""
    c = {}
    try:
        for it in json.load(open(os.path.join(HERE, "..", "info-trafic.json"), encoding="utf-8")).get("items", []):
            for b in it.get("b", []):
                if b.get("geo"):
                    r = b.get("r") or []
                    stop = next((r[i][0] for i in range(1, len(r)) if r[i][1] and re.search(r"arr[êe]ts?\s*$", r[i - 1][0], re.I)), "")
                    c[b["geo"]["a"] + "|" + stop] = [b["geo"]["lat"], b["geo"]["lon"]]
    except Exception:
        pass
    return c


def main():
    page = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else fetch()
    items = parse(page)
    if "--sans-adresses" not in sys.argv: add_geo(items, old_cache())
    if not items and "tetinfotraf" not in page:
        sys.exit("structure de la page inattendue : rien écrit")
    out = {"src": URL, "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
