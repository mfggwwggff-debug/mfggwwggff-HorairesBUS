# Horaires Grand Reims

Outil web pour le réseau Grand Reims Mobilités : calcul d'itinéraire, prochains passages, fiches horaires des lignes et plan du réseau avec la position estimée des bus.

- **Horaires théoriques** : fichier GTFS publié sur transport.data.gouv.fr (Licence ouverte).
- **Temps réel** : flux GTFS-RT du réseau, relu toutes les 30 secondes par le navigateur.
- Tout tourne dans le navigateur : pas de serveur, pas de compte, aucune donnée collectée.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `index.html` | La page publiée (horaires intégrés). Générée, ne pas modifier à la main. |
| `build/template.html` | Interface (HTML, CSS, JS). |
| `build/engine.js` | Calcul d'itinéraires et d'horaires. |
| `build/rt.js` | Lecture du flux temps réel. |
| `build/prep.py` | Convertit le GTFS en données compactes. |
| `build/make.py` | Reconstruit `index.html` : `python build/make.py gtfs.zip` |
| `.github/workflows/mise-a-jour-horaires.yml` | Mise à jour automatique deux fois par semaine. |

## Mise à jour

Automatique : le lundi et le jeudi, GitHub télécharge le dernier GTFS et republie la page si les horaires ont changé. On peut aussi la lancer à la main : onglet **Actions** → *Mise à jour des horaires* → **Run workflow**.
