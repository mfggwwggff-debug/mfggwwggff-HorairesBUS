-- Base du service d'alertes (#20). Rejouée à chaque mise en ligne : rien n'est effacé.
CREATE TABLE IF NOT EXISTS subs (id TEXT PRIMARY KEY, key TEXT NOT NULL, endpoint TEXT NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, prefs TEXT, created INTEGER, seen INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS subs_endpoint ON subs(endpoint);
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, sub TEXT NOT NULL, kind TEXT NOT NULL, at INTEGER NOT NULL, msg TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_at ON jobs(at);
CREATE INDEX IF NOT EXISTS jobs_sub ON jobs(sub, kind);
CREATE TABLE IF NOT EXISTS habits (id INTEGER PRIMARY KEY AUTOINCREMENT, sub TEXT NOT NULL, trip TEXT NOT NULL, at INTEGER NOT NULL, data TEXT NOT NULL, sent TEXT);
CREATE INDEX IF NOT EXISTS habits_at ON habits(at);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
-- #40 : journal des envois et comptage des réceptions
CREATE TABLE IF NOT EXISTS envois (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT, body TEXT, cible TEXT, nsub INTEGER, ok INTEGER DEFAULT 0, fail INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS envois_at ON envois(at);
CREATE TABLE IF NOT EXISTS recus (envoi INTEGER NOT NULL, sub TEXT NOT NULL, at INTEGER, vu INTEGER, PRIMARY KEY (envoi, sub));
CREATE INDEX IF NOT EXISTS recus_envoi ON recus(envoi);
-- #45 : erreurs relevées dans l'appli (une ligne par erreur distincte, page admin/)
CREATE TABLE IF NOT EXISTS erreurs (sig TEXT PRIMARY KEY, msg TEXT, src TEXT, stack TEXT, vue TEXT, app TEXT, ua TEXT, n INTEGER DEFAULT 1, tels TEXT, first INTEGER, last INTEGER);
-- #53 : infos trafic ajoutées à la main et pop-ups à l'ouverture (page admin/)
CREATE TABLE IF NOT EXISTS infos_main (id INTEGER PRIMARY KEY AUTOINCREMENT, t TEXT, txt TEXT, lines TEXT, niv TEXT, rt INTEGER DEFAULT 0, debut INTEGER, fin INTEGER, cree INTEGER, maj INTEGER);
CREATE TABLE IF NOT EXISTS popups (id INTEGER PRIMARY KEY AUTOINCREMENT, t TEXT, txt TEXT, btn TEXT, lien TEXT, debut INTEGER, fin INTEGER, cree INTEGER, maj INTEGER);
