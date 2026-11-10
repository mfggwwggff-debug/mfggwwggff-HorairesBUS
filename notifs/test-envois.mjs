// Essais hors ligne de l'outil d'envoi et du comptage (#40) : node notifs/test-envois.mjs
// Base SQLite en mémoire (node:sqlite) qui imite D1, envois web push interceptés.
import worker from "./worker.js";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";

// ---------- D1 en mémoire ----------
const db = new DatabaseSync(":memory:");
for (const s of fs.readFileSync(new URL("./schema.sql", import.meta.url), "utf8").split(";")) if (s.trim()) db.exec(s);
const DB = {
  prepare(sql) {
    const st = { args: [],
      bind(...a) { st.args = a; return st; },
      async run() { const r = db.prepare(sql).run(...st.args); return { meta: { last_row_id: Number(r.lastInsertRowid), changes: Number(r.changes) } }; },
      async first() { return db.prepare(sql).get(...st.args) ?? null; },
      async all() { return { results: db.prepare(sql).all(...st.args) }; } };
    return st;
  },
  async batch(sts) { const o = []; for (const s of sts) o.push(await s.run()); return o; },
};
const ADMIN_KEY = "cle-de-test-" + "x".repeat(20);
const env = { DB, ADMIN_KEY };

// ---------- web push intercepté ----------
const sent = [];
const vrai = globalThis.fetch;
globalThis.fetch = async (u, o) => {
  const s = String(u && u.url ? u.url : u);
  if (s.startsWith("https://push.test/")) { sent.push({ to: s, headers: o.headers }); return new Response(null, { status: 201 }); }
  if (s.startsWith("https://mort.test/")) return new Response(null, { status: 410 });
  throw new Error("appel réseau inattendu : " + s);
};

// ---------- outils ----------
const UA = { p256dh: "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4", auth: "BTBZMqHH6r4Tts7J_aSIgg" };
const b64u = (u8) => Buffer.from(u8).toString("base64url");
const unb64u = (s) => new Uint8Array(Buffer.from(s, "base64url"));
async function tok(n, sub) {
  const sec = unb64u(db.prepare("SELECT v FROM kv WHERE k = 'rsec'").get().v);
  const k = await crypto.subtle.importKey("raw", sec, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64u(new Uint8Array(await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(n + "|" + sub)))).slice(0, 16);
}
const post = (path, body) => worker.fetch(new Request("https://s.test" + path, { method: "POST", headers: { "Content-Type": "text/plain", Origin: "https://x.github.io", "CF-Connecting-IP": "1.2.3.4" }, body: JSON.stringify(body) }), env);
const adm = (op, extra) => post("/admin", Object.assign({ key: ADMIN_KEY, op }, extra));
const jr = async (r) => [r.status, await r.json()];

let ko = 0;
const ok = (nom, cond, vu) => { console.log((cond ? "  OK   " : "  RATÉ ") + nom + (cond ? "" : "  → " + JSON.stringify(vu))); if (!cond) ko++; };

// ---------- scénario ----------
console.log("Abonnement");
const [, ab] = await jr(await post("/abonner", { sub: { endpoint: "https://push.test/a1", keys: UA } }));
ok("deux téléphones abonnés", !!ab.id && !!ab.key, ab);
const [, ab2] = await jr(await post("/abonner", { sub: { endpoint: "https://push.test/a2", keys: UA } }));

console.log("Clé d'accès");
ok("clé refusée", (await post("/admin", { key: "mauvaise", op: "etat" })).status === 401);
const [, etat] = await jr(await adm("etat"));
ok("état : 2 téléphones", etat.phones.length === 2, etat.phones);
ok("rien n'est gardé d'autre que l'identifiant", Object.keys(etat.phones[0]).join(",") === "id,created,seen,lines,hab,trafic,quiet", etat.phones[0]);

console.log("Envoi à tous");
const [, env1] = await jr(await adm("envoyer", { titre: "Travaux place d'Erlon", corps: "Les U1 et U4 sont déviées.", url: "./#trafic" }));
ok("2 envoyées, 0 échec, 0 différé", env1.envoyes === 2 && env1.echecs === 0 && env1.differes === 0, env1);
ok("2 requêtes web push", sent.length === 2, sent.length);
ok("un en-tête Topic par envoi", sent.every((s) => s.headers.Topic === "m" + env1.n), sent.map((s) => s.headers.Topic));
let [, j1] = await jr(await adm("envois"));
ok("journal : 1 envoi, 2 envoyées, 0 reçue", j1.envois.length === 1 && j1.envois[0].ok === 2 && j1.envois[0].recus === 0, j1.envois[0]);

console.log("Réception signalée par sw.js");
ok("jeton inventé refusé", (await post("/recu", { n: env1.n, i: ab.id, k: "nimportequoi" })).status === 403);
ok("réception acceptée", (await post("/recu", { n: env1.n, i: ab.id, k: await tok(env1.n, ab.id) })).status === 200);
await post("/recu", { n: env1.n, i: ab.id, k: await tok(env1.n, ab.id) }); // doublon
[, j1] = await jr(await adm("envois"));
ok("1 reçue (doublon ignoré), 0 ouverte", j1.envois[0].recus === 1 && j1.envois[0].vus === 0, j1.envois[0]);
await post("/vu", { n: env1.n, i: ab2.id, k: await tok(env1.n, ab2.id) });
[, j1] = await jr(await adm("envois"));
ok("ouverture comptée aussi comme reçue", j1.envois[0].recus === 2 && j1.envois[0].vus === 1, j1.envois[0]);
const [, det] = await jr(await adm("detail", { n: env1.n }));
ok("détail : 2 lignes, identifiants seuls", det.recus.length === 2 && Object.keys(det.recus[0]).join(",") === "sub,at,vu", det.recus);

console.log("Heures calmes");
await post("/sync", { id: ab.id, key: ab.key, prefs: { quiet: true, qFrom: "00:00", qTo: "23:59", trafic: true } });
sent.length = 0;
const [, env2] = await jr(await adm("envoyer", { titre: "La nuit", corps: "Message de nuit." }));
ok("le téléphone en heures calmes attend", env2.envoyes === 1 && env2.differes === 1, env2);
sent.length = 0;
const [, env3] = await jr(await adm("envoyer", { titre: "Urgent", corps: "Réseau suspendu.", urgent: true }));
ok("cas urgent : tout part tout de suite", env3.envoyes === 2 && env3.differes === 0, env3);

console.log("Message différé repris par le déclencheur");
db.prepare("UPDATE jobs SET at = ? WHERE kind = 'msg'").run(Date.now() - 1000);
sent.length = 0;
await worker.scheduled({ scheduledTime: Date.now() }, env, {});
ok("le message de nuit est parti", sent.length === 1, sent.length);
const n2 = db.prepare("SELECT COUNT(*) n FROM envois WHERE id = ?").get(env2.n).n;
const ok2 = db.prepare("SELECT ok FROM envois WHERE id = ?").get(env2.n).ok;
ok("même numéro d'envoi, 2 envoyées au total", n2 === 1 && ok2 === 2, { n2, ok2 });

console.log("Alerte automatique journalisée");
db.prepare("INSERT INTO jobs (sub, kind, at, msg) VALUES (?, 'last', ?, ?)").run(ab.id, Date.now() - 1000, JSON.stringify({ title: "Dernier bus", body: "U3 dans 30 min", url: "./", tag: "last" }));
sent.length = 0;
await worker.scheduled({ scheduledTime: Date.now() }, env, {});
const last = db.prepare("SELECT * FROM envois WHERE kind = 'last'").get();
ok("un envoi « dernier bus » compté", sent.length === 1 && last && last.ok === 1, last);
const [, st] = await jr(await adm("stats"));
ok("statistiques par type", st.stats.some((x) => x.kind === "msg") && st.stats.some((x) => x.kind === "last"), st.stats);

console.log("Abonnement mort");
db.prepare("UPDATE subs SET endpoint = 'https://mort.test/a2' WHERE id = ?").run(ab2.id);
const [, env4] = await jr(await adm("envoyer", { titre: "Après la mort", corps: "x" }));
ok("échec compté et abonnement effacé", env4.echecs === 1 && db.prepare("SELECT COUNT(*) n FROM subs").get().n === 1, env4);

console.log("Garde-fous");
ok("lien hors de l'appli refusé", (await adm("envoyer", { titre: "x", url: "https://ailleurs.test" })).status === 400);
ok("titre vide refusé", (await adm("envoyer", { titre: "   " })).status === 400);
ok("opération inconnue refusée", (await adm("nawak")).status === 400);
ok("sans clé réglée, l'outil est fermé", (await worker.fetch(new Request("https://s.test/admin", { method: "POST", body: "{}" }), { DB })).status === 503);

globalThis.fetch = vrai;
console.log(ko ? "\n" + ko + " essai(s) raté(s)" : "\nTout est passé");
process.exit(ko ? 1 : 0);
