"""Reconstruit index.html à partir d'un GTFS (dossier décompressé ou .zip).
Usage : python build/make.py chemin/vers/gtfs.zip
        python build/make.py --data   (sans retraiter le GTFS : réutilise build/data.json)
        python build/make.py --data --test   (version d'essai dans test/index.html, la page normale ne bouge pas)
"""
import sys, os, zipfile, tempfile, subprocess, json

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
args = [a for a in sys.argv[1:] if a != "--test"]
test = "--test" in sys.argv[1:]
src = args[0]
data = os.path.join(here, "data.json")
if src != "--data":
    if src.endswith(".zip"):
        tmp = tempfile.mkdtemp()
        zipfile.ZipFile(src).extractall(tmp)
        src = tmp
    subprocess.run([sys.executable, os.path.join(here, "prep.py"), src, data], check=True)

HEAD = """<meta name="theme-color" content="#ea5a14">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Horaires">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" type="image/png" href="icon-192.png">"""

t = open(os.path.join(here, "template.html"), encoding="utf-8").read()
d = open(data, encoding="utf-8").read().replace("</", "<\\/")
e = "\n".join(open(os.path.join(here, f), encoding="utf-8").read() for f in ("engine.js", "rt.js", "assets.js"))
t = t.replace("/*__MAP__*/", open(os.path.join(here, "map.js"), encoding="utf-8").read(), 1).replace("<!--__HEAD__-->", HEAD, 1).replace("__DATA__", d, 1).replace("/*__ENGINE__*/", e, 1)
out = os.path.join(root, "index.html")
if test:
    # même page, servie depuis test/ : les fichiers partagés sont un dossier plus haut
    for a, b in (('href="manifest.webmanifest"', 'href="../manifest.webmanifest"'), ('href="apple-touch-icon.png"', 'href="../apple-touch-icon.png"'),
                 ('"icon-192.png"', '"../icon-192.png"'), ('"info-trafic.json?v="', '"../info-trafic.json?v="'),
                 ('"plans/', '"../plans/'), ("'plans/", "'../plans/"), ('register("sw.js")', 'register("../sw.js")')):
        t = t.replace(a, b)
    t = t.replace("<title>", "<title>[TEST] ", 1)
    os.makedirs(os.path.join(root, "test"), exist_ok=True)
    out = os.path.join(root, "test", "index.html")
open(out, "w", encoding="utf-8").write(t)
feed = json.loads(open(data, encoding="utf-8").read())["feed"]
print(os.path.relpath(out, root), "reconstruit :", feed)
