"""#74 : tous les arrêts du GTFS, même ceux qu'aucune ligne ne dessert, pour placer les arrêts provisoires des
déviations dans admin/ (un clic sur un arrêt existant : l'appli sait où il est et fait les correspondances).

Usage : python build/arrets_gtfs.py gtfs.zip > arrets-gtfs.json
Sortie : {"s": [[nom, lat, lon, desservi (1/0), stop_id], …]} ; pour un arrêt desservi, le nom est celui de l'appli
(build/data.json), pour les autres il est mis en forme comme dans prep.py (`nice`).
"""
import sys, os, io, csv, json, zipfile, ast

here = os.path.dirname(os.path.abspath(__file__))
# la mise en forme des noms de prep.py, sans lancer la conversion
src = open(os.path.join(here, "prep.py"), encoding="utf-8").read()
mod = ast.parse(src)
keep = [n for n in mod.body if (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("SMALL", "UP", "ACC") for t in n.targets)) or (isinstance(n, ast.FunctionDef) and n.name == "nice")]
ns = {"re": __import__("re")}
exec(compile(ast.Module(body=keep, type_ignores=[]), "prep.py", "exec"), ns)
nice = ns["nice"]

z = zipfile.ZipFile(sys.argv[1])
rd = lambda f: csv.DictReader(io.TextIOWrapper(z.open(f), encoding="utf-8-sig"))
used = {r["stop_id"] for r in rd("stop_times.txt")}
D = json.load(open(os.path.join(here, "data.json"), encoding="utf-8"))
app = {sid: D["P"][D["Q"][i][0]][0] for i, sid in enumerate(D["QI"])}
out = []
for r in rd("stops.txt"):
    if r.get("location_type", "") not in ("", "0"): continue
    try: la, lo = round(float(r["stop_lat"]), 6), round(float(r["stop_lon"]), 6)
    except ValueError: continue
    sid = r["stop_id"]
    out.append([app.get(sid) or nice(r["stop_name"]), la, lo, 1 if sid in used else 0, sid])
out.sort(key=lambda x: (x[0], x[4]))
json.dump({"s": out}, sys.stdout, ensure_ascii=False, separators=(",", ":"))
print()
