import json, urllib.request, urllib.parse
out=[]
for q,lat,lon in [("18 rue Aristide Briand",49.222676,4.053037),("18 rue Aristide Briand Cormontreuil",49.222676,4.053037),("20 rue Aristide Briand",49.222676,4.053037),("rond point Route de Taissy Cormontreuil",None,None),("Voie Verte Route de Taissy Cormontreuil",None,None)]:
    p={"q":q,"limit":3,"index":"address"}
    if lat: p.update(lat=lat,lon=lon)
    try:
        r=json.load(urllib.request.urlopen(urllib.request.Request("https://data.geopf.fr/geocodage/search?"+urllib.parse.urlencode(p),headers={"User-Agent":"horaires-grand-reims"}),timeout=15))
        out.append([q,[(f["properties"].get("label"),f["properties"].get("score"),f["properties"].get("type"),f["geometry"]["coordinates"]) for f in r["features"]]])
    except Exception as e: out.append([q,str(e)])
json.dump(out,open("debug-geo.json","w"),ensure_ascii=False,indent=1)
