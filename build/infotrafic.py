"""Relève l'info trafic publiée sur grandreims-mobilites.fr et écrit info-trafic.json.

Le site n'a pas de flux de données ouvert et bloque la lecture depuis une autre page : ce script
tourne dans GitHub Actions (toutes les 15 minutes environ) et l'appli relit le fichier produit.

Usage : python build/infotrafic.py [fichier_html_local] > info-trafic.json
Sans argument, la page est téléchargée. Bibliothèque standard uniquement.
"""
import sys, re, json, html, hashlib, datetime as dt, urllib.request

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


def parse(page):
    items = []
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
        items.append({"id": iid, "t": title, "lines": ls, "p": period, "start": start, "end": end, "b": blocks})
    return items


def main():
    page = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else fetch()
    items = parse(page)
    if not items and "tetinfotraf" not in page:
        sys.exit("structure de la page inattendue : rien écrit")
    out = {"src": URL, "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
