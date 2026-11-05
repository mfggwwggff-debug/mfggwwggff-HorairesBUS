"""Version pour claude.ai (artifact) : même page, sans les balises d'installation sur l'écran d'accueil.
Usage : python build.py   (depuis le dossier build/) -> horaires-grand-reims.html
"""
t = open("template.html").read()
d = open("data.json").read().replace("</", "<\\/")
e = "\n".join(open(f).read() for f in ("engine.js", "rt.js", "assets.js"))
t = t.replace("/*__MAP__*/", open("map.js").read(), 1).replace("<!--__HEAD__-->", "", 1).replace("__DATA__", d, 1).replace("/*__ENGINE__*/", e, 1)
open("horaires-grand-reims.html", "w").write(t)
print(len(t))
