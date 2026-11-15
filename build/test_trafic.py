"""Banc d'essai du classement de l'info trafic : rejoue toutes les infos de build/trafic-archive.json.

  python build/test_trafic.py            résultat : erreurs (classement ≠ attendu), infos à vérifier, changements
  python build/test_trafic.py --detail   avec, pour chaque info en erreur, les phrases lues et ce qui y a été reconnu

Code de sortie 1 s'il y a au moins une erreur : à lancer après chaque changement de build/trafic_classe.py.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trafic_classe as T

CHAMPS = ("grav", "nat", "portee")


def main():
    a = json.load(open(os.path.join(HERE, "trafic-archive.json"), encoding="utf-8"))
    arr = T.Arrets()
    err, averif, change, ok = [], [], [], 0
    for k, it in a["infos"].items():
        c = T.classe(it, arr.nb_lignes)
        st = {n: arr.trouve(n, it.get("lines") or []) for n in T.arrets_cites(it)}
        att, lab = it.get("attendu"), ("[exemple] " if it.get("exemple") else "") + it["t"][:70]
        if att:
            diff = [f"{x} : {c[x]} au lieu de {att[x]}" for x in CHAMPS if x in att and c[x] != att[x]]
            for n, v in (att.get("arrets") or {}).items():
                if st.get(n) != v: diff.append(f"arrêt « {n} » : {st.get(n)} au lieu de {v}")
            if diff: err.append((lab, diff, c))
            else: ok += 1
        if not att or not c["sur"] or any(v is None for v in st.values()):
            why = []
            if not att: why.append("pas encore vérifiée")
            if not c["sur"]: why.append("rien de reconnu")
            why += [f"arrêt « {n} » introuvable" for n, v in st.items() if v is None]
            averif.append((lab, why, c))
        if it.get("auto") and any(c[x] != it["auto"][x] for x in CHAMPS):
            change.append((lab, ", ".join(f"{x} {it['auto'][x]} → {c[x]}" for x in CHAMPS if c[x] != it["auto"][x])))

    print(f"{len(a['infos'])} infos rejouées : {ok} conformes, {len(err)} en erreur, {len(averif)} à vérifier\n")
    if err:
        print("ERREURS")
        for lab, diff, c in err:
            print(" -", lab); [print("     ", d) for d in diff]
            if "--detail" in sys.argv: [print("        lu :", p, "→", ", ".join(e)) for p, e in c["pourquoi"]]
        print()
    if averif:
        print("À VÉRIFIER")
        for lab, why, c in averif: print(f" - {lab} ({'; '.join(why)}) → {c['grav']}, {c['nat']}, {c['portee']}")
        print()
    if change:
        print("CLASSEMENT DIFFÉRENT DE CELUI DU JOUR D'APPARITION")
        for lab, d in change: print(" -", lab, ":", d)
    sys.exit(1 if err else 0)


if __name__ == "__main__":
    main()
