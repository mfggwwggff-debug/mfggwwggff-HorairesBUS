"""Reconstruit index.html à partir d'un GTFS (dossier décompressé ou .zip).
Usage : python build/make.py chemin/vers/gtfs.zip
"""
import sys, os, zipfile, tempfile, subprocess, json

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
src = sys.argv[1]
if src.endswith(".zip"):
    tmp = tempfile.mkdtemp()
    zipfile.ZipFile(src).extractall(tmp)
    src = tmp
data = os.path.join(here, "data.json")
subprocess.run([sys.executable, os.path.join(here, "prep.py"), src, data], check=True)

HEAD = """<meta name="theme-color" content="#c8001a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Horaires">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" type="image/png" href="icon-192.png">"""

t = open(os.path.join(here, "template.html"), encoding="utf-8").read()
d = open(data, encoding="utf-8").read().replace("</", "<\\/")
e = open(os.path.join(here, "engine.js"), encoding="utf-8").read() + "\n" + open(os.path.join(here, "rt.js"), encoding="utf-8").read()
t = t.replace("<!--__HEAD__-->", HEAD, 1).replace("__DATA__", d, 1).replace("/*__ENGINE__*/", e, 1)
open(os.path.join(root, "index.html"), "w", encoding="utf-8").write(t)
feed = json.loads(open(data, encoding="utf-8").read())["feed"]
print("index.html reconstruit :", feed)
