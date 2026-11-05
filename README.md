# Horaires Grand Reims

Outil web pour le réseau Grand Reims Mobilités, pensé pour le téléphone : accueil avec arrêts favoris et arrêts autour de soi, calcul d'itinéraire, prochains passages, suivi d'un bus, fiches horaires et plan du réseau avec la position estimée des bus.

- **Horaires théoriques** : fichier GTFS publié sur transport.data.gouv.fr (Licence ouverte).
- **Temps réel** : flux GTFS-RT du réseau, relu toutes les 30 secondes par le navigateur.
- **Info trafic** : relevée sur grandreims-mobilites.fr toutes les 15 minutes environ par GitHub Actions, dans `info-trafic.json`.
- **Fond de carte** : tuiles OpenStreetMap, adoucies en gris.
- Tout tourne dans le navigateur : pas de serveur, pas de compte, aucune donnée collectée.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `index.html` | La page publiée (horaires intégrés). Générée, ne pas modifier à la main. |
| `build/template.html` | Interface (HTML, CSS, JS). |
| `build/engine.js` | Calcul d'itinéraires et d'horaires. |
| `build/rt.js` | Lecture du flux temps réel. |
| `build/map.js` | Plan interactif et position estimée des bus. |
| `build/prep.py` | Convertit le GTFS en données compactes. |
| `build/post.py` | Tram T1/T2, couleurs de texte des pastilles, dessin en parallèle des tronçons communs. |
| `build/assets.js` | Logo Grand Reims Mobilités (vectoriel) et logos des lignes. |
| `build/infotrafic.py` | Relève l'info trafic du site du réseau. |
| `info-trafic.json` | Info trafic relevée (générée, ne pas modifier à la main). |
| `build/make.py` | Reconstruit `index.html` : `python build/make.py gtfs.zip` (ou `--data` pour réutiliser `build/data.json`) |
| `.github/workflows/mise-a-jour-horaires.yml` | Mise à jour automatique deux fois par semaine. |
| `.github/workflows/info-trafic.yml` | Relevé de l'info trafic toutes les 15 minutes. |

## Mise à jour

Automatique : le lundi et le jeudi, GitHub télécharge le dernier GTFS et republie la page si les horaires ont changé. On peut aussi la lancer à la main : onglet **Actions** → *Mise à jour des horaires* → **Run workflow**.
