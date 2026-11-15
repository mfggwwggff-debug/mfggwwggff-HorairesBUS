// Essais hors ligne de la surveillance du temps réel (#46) : node notifs/test-rt.mjs
// Base SQLite en mémoire qui imite D1, flux GTFS-RT fabriqué, envois web push interceptés.
import worker from "./worker.js";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";

const db = new DatabaseSync(":memory:");
for (const s of fs.readFileSync(new URL("./schema.sql", import.meta.url), "utf8").split(";")) if (s.trim()) db.exec(s);
const DB = {
  prepare(sql) {
    const st = { args: [], bind(...a) { st.args = a; return st; },
      async run() { const r = db.prepare(sql).run(...st.args); return { meta: { last_row_id: Number(r.lastInsertRowid), changes: Number(r.changes) } }; },
      async first() { return db.prepare(sql).get(...st.args) ?? null; },
      async all() { return { results: db.prepare(sql).all(...st.args) }; } };
    return st;
  },
  async batch(sts) { const o = []; for (const s of sts) o.push(await s.run()); return o; },
};
const ADMIN_KEY = "cle-de-test-" + "x".repeat(20);
const env = { DB, ADMIN_KEY };

// ---------- flux fabriqué ----------
const varint = (n) => { const o = []; do { let b = n & 127; n = Math.floor(n / 128); if (n) b |= 128; o.push(b); } while (n); return o; };
const field = (f, bytes) => [...varint(f * 8 + 2), ...varint(bytes.length), ...bytes];
const str = (s) => [...new TextEncoder().encode(s)];
const feedOf = (ids) => new Uint8Array([...field(1, field(1, str("2.0"))), ...ids.flatMap((id, i) => field(2, [...field(1, str("e" + i)), ...field(3, field(1, field(1, str(id))))]))]);
const REF = JSON.parse(fs.readFileSync(new URL("../rt-ref.json", import.meta.url), "utf8"));
const d0 = Date.UTC(+REF.d0.slice(0, 4), +REF.d0.slice(4, 6) - 1, +REF.d0.slice(6, 8));
const k = 4, T0 = d0 + k * 864e5 + 13 * 3600e3; // 14 h à Paris, 5e jour des horaires
const today = [];
REF.t.forEach((row, sv) => { if (row && REF.S[sv][k] === "1") for (const c of row.split(" ")) { const [n, s] = c.split("."); if (n) today.push(n + "-" + REF.suf[+s]); } });
const ids = today.slice(0, 120);
let FLUX = ids;
const sent = [];
globalThis.fetch = async (u, o) => {
  const s = String(u && u.url ? u.url : u);
  if (s.startsWith("https://push.test/")) { sent.push(s); return new Response(null, { status: 201 }); }
  if (s.includes("gtfs-rt")) return new Response(feedOf(FLUX));
  if (s.includes("rt-ref.json")) return new Response(JSON.stringify(REF));
  if (s.includes("grandreims-mobilites")) return new Response("<html></html>");
  throw new Error("appel réseau inattendu : " + s);
};
const UA = { p256dh: "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4", auth: "BTBZMqHH6r4Tts7J_aSIgg" };
const post = (path, body) => worker.fetch(new Request("https://s.test" + path, { method: "POST", headers: { "Content-Type": "text/plain", "CF-Connecting-IP": "1.2.3.4" }, body: JSON.stringify(body) }), env);
const adm = async (op, extra) => (await post("/admin", Object.assign({ key: ADMIN_KEY, op }, extra))).json();
const tick = (min) => worker.scheduled({ scheduledTime: T0 + min * 60000 }, env);
let ko = 0;
const ok = (nom, cond, vu) => { console.log((cond ? "  OK   " : "  RATÉ ") + nom + (cond ? "" : "  → " + JSON.stringify(vu))); if (!cond) ko++; };

const a1 = await (await post("/abonner", { sub: { endpoint: "https://push.test/a1", keys: UA } })).json();
await post("/abonner", { sub: { endpoint: "https://push.test/a2", keys: UA } });

console.log("Relevé");
await tick(0); let e = await adm("etat");
ok("flux conforme : ok, 120 sur 120", e.rt.statut === "ok" && e.rt.matched === 120 && e.rt.total === 120, e.rt);
FLUX = ids.map((x) => x.replace(/-[^-]+$/, "-2026_SEPT-_REZO-Semaine-99"));
await tick(5); e = await adm("etat");
ok("calendrier renuméroté : repli par le numéro", e.rt.statut === "repli" && e.rt.matched === 120 && e.rt.exact === 0, e.rt);
FLUX = []; await tick(10); e = await adm("etat");
ok("flux vide : « vide », pas de panne", e.rt.statut === "vide", e.rt);

console.log("Alerte de panne");
ok("téléphone inconnu refusé", !!(await adm("rtAlerte", { sub: "zzzz" })).error);
ok("téléphone choisi", (await adm("rtAlerte", { sub: a1.id })).rtSub === a1.id);
FLUX = ["999999999-x", "888888888-y"];
await tick(15); ok("panne au premier relevé : pas encore d'alerte", sent.length === 0, sent);
await tick(20); ok("5 min plus tard : toujours pas", sent.length === 0, sent);
await tick(25); ok("10 min : alerte, à ce seul téléphone", sent.length === 1 && sent[0] === "https://push.test/a1", sent);
await tick(30); ok("pas de seconde alerte pendant la même panne", sent.length === 1, sent);
e = await adm("etat"); ok("page admin : panne depuis 14 h 15", e.rt.statut === "panne" && e.rt.depuis === T0 + 15 * 60000, e.rt);
FLUX = ids; await tick(35);
ok("retour : « rétabli », au même téléphone", sent.length === 2 && sent[1] === "https://push.test/a1", sent);
const j = await adm("envois");
ok("envois journalisés en « rt »", j.envois.filter((x) => x.kind === "rt").length === 2, j.envois);
await adm("rtAlerte", { sub: "" });
FLUX = ["1-x"]; for (const m of [40, 45, 50, 55]) await tick(m);
ok("plus personne choisi : aucune alerte", sent.length === 2, sent);

console.log(ko ? `\n${ko} essai(s) raté(s)` : "\nTout est passé");
process.exit(ko ? 1 : 0);
