"""Télécharge les plans du réseau publiés sur grandreims-mobilites.fr et les convertit en images.

Sortie : dossier plans/ avec, pour chaque PDF, une vignette et une image par page, et plans/plans.json.
Nécessite pdftoppm (paquet poppler-utils). Tourne dans GitHub Actions une fois par semaine.
Usage : python build/plans.py
"""
import os, re, sys, json, html, hashlib, subprocess, tempfile, shutil, urllib.request, urllib.parse

PAGE = "https://www.grandreims-mobilites.fr/fr/w48-Telecharger-les-plans-du-reseau.html"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "plans")
UA = {"User-Agent": "Mozilla/5.0 (compatible; horaires-grand-reims; +https://github.com/mfggwwggff-debug/mfggwwggff-HorairesBUS)"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def title_of(label, line):
    t = re.sub(r"^\s*T[ée]l[ée]charger\s+", "", label, flags=re.I)
    t = t.replace("périrubain", "périurbain")
    t = re.sub(r"^(le|la|les)\s+", "", t, flags=re.I)
    if line and re.match(r"plan de la ligne|plan ligne", t, re.I):
        t = "Ligne " + line
    elif line and t.lower().startswith("plan de la ligne"):
        t = "Ligne " + line
    return t[:1].upper() + t[1:]


def find_plans(page):
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"]*?/upload/PLANS/[^"]+?\.pdf[^"]*)"[^>]*>(.*?)</a>', page, re.S | re.I):
        href, label = html.unescape(m.group(1)), text(m.group(2))
        im = re.findall(r"__IndicesLignes/([a-z0-9]+?)(?:-\d+)?\.png", m.group(0), re.I)
        line = im[-1].upper() if im else ""
        if line == "SUB": line = "Sub"
        url = urllib.parse.urljoin(PAGE, href)
        if any(p["pdf"].split("?")[0] == url.split("?")[0] for p in out):
            continue
        out.append({"title": title_of(label, line), "line": line, "pdf": url})
    return out


def slug(s):
    s = s.lower()
    s = s.translate(str.maketrans("éèêëàâäîïôöûüç", "eeeeaaaiioouuc"))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:48] or "plan"


def render(pdf_path, prefix):
    """Une image JPEG par page (2600 px de large au plus) + une vignette de la 1re page."""
    tmp = tempfile.mkdtemp()
    subprocess.run(["pdftoppm", "-jpeg", "-jpegopt", "quality=82,progressive=y", "-scale-to", "2600", pdf_path, os.path.join(tmp, "p")], check=True)
    subprocess.run(["pdftoppm", "-jpeg", "-jpegopt", "quality=78", "-scale-to", "520", "-f", "1", "-l", "1", pdf_path, os.path.join(tmp, "t")], check=True)
    pages = []
    for f in sorted(os.listdir(tmp)):
        if not f.startswith("p-"): continue
        n = int(re.search(r"(\d+)", f).group(1))
        dst = f"{prefix}-{n}.jpg"
        shutil.move(os.path.join(tmp, f), os.path.join(OUT, dst))
        pages.append(dst)
    thumb = next(f for f in os.listdir(tmp) if f.startswith("t-"))
    shutil.move(os.path.join(tmp, thumb), os.path.join(OUT, f"{prefix}-vignette.jpg"))
    shutil.rmtree(tmp)
    return pages, f"{prefix}-vignette.jpg"


def size_of(path):
    """Largeur et hauteur d'un JPEG (lecture de l'en-tête SOF)."""
    import struct
    f = open(path, "rb").read()
    i = 2
    while i + 9 < len(f):
        if f[i] != 0xFF: i += 1; continue
        m = f[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", f[i + 5:i + 9]); return w, h
        i += 2 + struct.unpack(">H", f[i + 2:i + 4])[0]
    return 0, 0


def main():
    os.makedirs(OUT, exist_ok=True)
    idx_path = os.path.join(OUT, "plans.json")
    old = json.load(open(idx_path)) if os.path.exists(idx_path) else {"plans": []}
    known = {p["pdf"].split("?")[0]: p for p in old.get("plans", [])}
    found = find_plans(get(PAGE).decode("utf-8", "replace"))
    if not found:
        sys.exit("aucun plan trouvé : structure de la page inattendue")
    plans, keep = [], set()
    for p in found:
        data = get(p["pdf"])
        sha = hashlib.sha1(data).hexdigest()[:12]
        prev = known.get(p["pdf"].split("?")[0])
        prefix = slug(p["title"])
        if prev and prev.get("sha") == sha and all(os.path.exists(os.path.join(OUT, x["src"])) for x in prev["pages"]):
            entry = {**prev, "title": p["title"], "line": p["line"]}
        else:
            for f in os.listdir(OUT):
                if f.startswith(prefix + "-"): os.remove(os.path.join(OUT, f))
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
                fh.write(data); pdf = fh.name
            pages, thumb = render(pdf, prefix)
            os.remove(pdf)
            entry = {"id": prefix, "title": p["title"], "line": p["line"], "pdf": p["pdf"], "sha": sha, "mb": round(len(data) / 1e6, 1),
                     "thumb": thumb, "pages": [dict(zip(("src", "w", "h"), (x, *size_of(os.path.join(OUT, x))))) for x in pages]}
            print("nouveau ou modifié :", p["title"])
        plans.append(entry)
        keep.update([entry["thumb"]] + [x["src"] for x in entry["pages"]])
    for f in os.listdir(OUT):
        if f.endswith(".jpg") and f not in keep: os.remove(os.path.join(OUT, f))
    json.dump({"src": PAGE, "plans": plans}, open(idx_path, "w"), ensure_ascii=False, indent=1)
    print(len(plans), "plans")


if __name__ == "__main__":
    main()
