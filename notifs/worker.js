// Service d'alertes de l'appli Horaires Grand Reims (#20) : Cloudflare Worker + base D1.
// Le téléphone fait les calculs (dernier bus, bus habituel, suivi) et confie au service ce qu'il faut envoyer et quand ;
// le service garde ces envois, relit le temps réel des bus habituels et relève l'info trafic toutes les 5 min.
// Notifications « web push » chiffrées (RFC 8291) et signées (VAPID, RFC 8292) avec WebCrypto, sans bibliothèque.

const RT_URL = "https://proxy.transport.data.gouv.fr/resource/fluo-citura-reims-gtfs-rt";
const TRAFIC_URL = "https://www.grandreims-mobilites.fr/fr/1JA-Info-trafic.html";
const CONTACT = "https://github.com/mfggwwggff-debug/mfggwwggff-HorairesBUS";
const ALIAS = { CITYBUS: "C", TRAM: "T1,T2", T: "T1,T2", A: "T1", B: "T2" };
const MAX_SENDS = 15; // par passage (limites de l'offre gratuite : 50 requêtes sortantes, 10 ms de calcul)

// ---------- outils ----------
const enc = new TextEncoder(), dec = new TextDecoder();
const b64u = (u8) => { let s = ""; for (const b of u8) s += String.fromCharCode(b); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); };
const unb64u = (s) => { s = s.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "="; return Uint8Array.from(atob(s), (c) => c.charCodeAt(0)); };
const cat = (...a) => { const o = new Uint8Array(a.reduce((n, x) => n + x.length, 0)); let p = 0; for (const x of a) { o.set(x, p); p += x.length; } return o; };
async function hmac(key, data) { const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]); return new Uint8Array(await crypto.subtle.sign("HMAC", k, data)); }
const rand = (n) => crypto.getRandomValues(new Uint8Array(n));
const json = (o, st = 200, h = {}) => new Response(JSON.stringify(o), { status: st, headers: { "content-type": "application/json", ...h } });

// ---------- chiffrement aes128gcm (RFC 8291) ----------
// asKeys / salt : seulement pour les essais (vecteur de la RFC) ; sinon tirés au hasard.
export async function encryptPush(plain, p256dh, auth, asKeys, salt) {
  const ua = unb64u(p256dh), secret = unb64u(auth);
  const as = asKeys || await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const asPub = new Uint8Array(await crypto.subtle.exportKey("raw", as.publicKey));
  const uaKey = await crypto.subtle.importKey("raw", ua, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const ecdh = new Uint8Array(await crypto.subtle.deriveBits({ name: "ECDH", public: uaKey }, as.privateKey, 256));
  const prkKey = await hmac(secret, ecdh);
  const ikm = await hmac(prkKey, cat(enc.encode("WebPush: info\0"), ua, asPub, new Uint8Array([1])));
  salt = salt || rand(16);
  const prk = await hmac(salt, ikm);
  const cek = (await hmac(prk, cat(enc.encode("Content-Encoding: aes128gcm\0"), new Uint8Array([1])))).slice(0, 16);
  const nonce = (await hmac(prk, cat(enc.encode("Content-Encoding: nonce\0"), new Uint8Array([1])))).slice(0, 12);
  const k = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["encrypt"]);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, k, cat(enc.encode(plain), new Uint8Array([2]))));
  const hdr = new Uint8Array(21); hdr.set(salt, 0); new DataView(hdr.buffer).setUint32(16, 4096); hdr[20] = asPub.length;
  return cat(hdr, asPub, ct);
}

// ---------- clés VAPID : créées au premier besoin, gardées dans la base ----------
let VAPID = null; const JWTS = new Map();
async function vapid(env) {
  if (VAPID) return VAPID;
  const row = await env.DB.prepare("SELECT v FROM kv WHERE k = 'vapid'").first();
  let jwk, pub;
  if (row) ({ jwk, pub } = JSON.parse(row.v));
  else {
    const kp = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
    jwk = await crypto.subtle.exportKey("jwk", kp.privateKey);
    pub = b64u(new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey)));
    await env.DB.prepare("INSERT OR IGNORE INTO kv (k, v) VALUES ('vapid', ?)").bind(JSON.stringify({ jwk, pub })).run();
    const again = await env.DB.prepare("SELECT v FROM kv WHERE k = 'vapid'").first(); ({ jwk, pub } = JSON.parse(again.v));
  }
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  return (VAPID = { key, pub });
}
async function vapidHeader(env, endpoint) {
  const v = await vapid(env), aud = new URL(endpoint).origin, now = Math.floor(Date.now() / 1000);
  const c = JWTS.get(aud); if (c && c.exp - now > 3600) return c.h;
  const exp = now + 12 * 3600;
  const unsigned = b64u(enc.encode(JSON.stringify({ typ: "JWT", alg: "ES256" }))) + "." + b64u(enc.encode(JSON.stringify({ aud, exp, sub: CONTACT })));
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, v.key, enc.encode(unsigned)));
  const h = `vapid t=${unsigned}.${b64u(sig)}, k=${v.pub}`;
  JWTS.set(aud, { exp, h }); return h;
}

// Envoie une notification ; rend false si l'abonnement est mort (à effacer).
async function sendPush(env, sub, msg, topic) {
  const body = await encryptPush(JSON.stringify(msg), sub.p256dh, sub.auth);
  const headers = { "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", TTL: "900", Urgency: "high", Authorization: await vapidHeader(env, sub.endpoint) };
  if (topic) headers.Topic = topic.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 32);
  const r = await fetch(sub.endpoint, { method: "POST", headers, body });
  if (r.status === 404 || r.status === 410) return false;
  return true;
}

// ---------- heure de Paris ----------
const fmtParis = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const parisMin = (ms) => { const [h, m] = fmtParis.format(new Date(ms)).split(":").map(Number); return h * 60 + m; };
const hm2min = (s) => { const [h, m] = String(s || "0:0").split(":").map(Number); return h * 60 + m; };
// Fin des heures calmes (epoch ms) si on est dedans, sinon 0.
function quietUntil(prefs, now) {
  if (!prefs.quiet) return 0;
  const a = hm2min(prefs.qFrom || "22:30"), b = hm2min(prefs.qTo || "06:30"), m = parisMin(now);
  const inQ = a <= b ? m >= a && m < b : m >= a || m < b;
  if (!inQ) return 0;
  const left = (b - m + 1440) % 1440;
  return now + left * 60000;
}

// ---------- temps réel : retard d'une course à un arrêt ----------
function pb(buf) {
  let p = 0;
  const varint = () => { let r = 0, m = 1, b, n = 0; const st = p; do { b = buf[p++]; r += (b & 127) * m; m *= 128; n++; } while (b & 128);
    if (n < 8) return r; let big = 0n, sh = 0n; for (let i = st; i < p; i++) { big |= BigInt(buf[i] & 127) << sh; sh += 7n; } return Number(BigInt.asIntN(64, big)); };
  return { end: () => p >= buf.length, tag: () => { const t = varint(); return [Math.floor(t / 8), t & 7]; }, varint,
    bytes: () => { const n = varint(); const s = buf.subarray(p, p + n); p += n; return s; },
    skip: (w) => { if (w === 0) varint(); else if (w === 1) p += 8; else if (w === 2) { const n = varint(); p += n; } else if (w === 5) p += 4; else throw new Error("wire " + w); } };
}
function msg(buf, f) { const r = pb(buf), o = {}; while (!r.end()) { const [k, w] = r.tag(); if (f[k]) f[k](r, o, w); else r.skip(w); } return o; }
const strF = (name) => (r, o) => { o[name] = dec.decode(r.bytes()); };
const intF = (name) => (r, o) => { o[name] = r.varint(); };
const EV = { 1: intF("delay"), 2: intF("time") };
const STU = { 1: intF("seq"), 2: (r, o) => { o.arr = msg(r.bytes(), EV); }, 3: (r, o) => { o.dep = msg(r.bytes(), EV); }, 4: strF("stop_id") };
// Relit le flux et rend Map(trip_id → liste des mises à jour d'arrêt), seulement pour les courses demandées.
export function rtTrips(u8, wanted) {
  const out = new Map(), feed = pb(u8);
  while (!feed.end()) {
    const [f, w] = feed.tag();
    if (f !== 2) { feed.skip(w); continue; }
    const ent = pb(feed.bytes());
    while (!ent.end()) {
      const [g, w2] = ent.tag();
      if (g !== 3) { ent.skip(w2); continue; }
      const tu = ent.bytes(), r = pb(tu); let id = null; const stus = [];
      while (!r.end()) {
        const [h, w3] = r.tag();
        if (h === 1) { const td = msg(r.bytes(), { 1: strF("trip_id") }); id = td.trip_id; if (!wanted.has(id)) break; }
        else if (h === 2) stus.push(r.bytes());
        else r.skip(w3);
      }
      if (id && wanted.has(id)) out.set(id, stus.map((b) => msg(b, STU)));
    }
  }
  return out;
}
// Heure de passage estimée (epoch s) à l'arrêt i de la course : ids = stop_id des arrêts 0..i, sched = départs théoriques (epoch s).
export function etaAt(stus, ids, sched) {
  const i = ids.length - 1; let best = -1, t = null;
  for (const s of stus || []) {
    let j = s.stop_id ? ids.indexOf(s.stop_id) : -1;
    if (j < 0 && s.seq) j = s.seq - 1;
    if (j < 0 || j > i || j < best) continue;
    const e = (j === i ? (s.arr || s.dep) : (s.dep || s.arr)) || null; if (!e) continue;
    const v = e.time || (e.delay !== undefined ? sched[j] + e.delay : null); if (v == null) continue;
    best = j; t = j === i ? v : sched[i] + (v - sched[j]);
  }
  return best < 0 ? { eta: sched[i], live: false } : { eta: t, live: true, delay: Math.round((t - sched[i]) / 60) };
}

// ---------- info trafic ----------
const textOf = (s) => s.replace(/<br\s*\/?>/gi, " ").replace(/<[^>]+>/g, "").replace(/&nbsp;|&#160;/g, " ").replace(/&amp;/g, "&").replace(/&#0?39;|&apos;|&rsquo;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n)).replace(/&([a-z]+);/gi, (x, n) => ENT[n] || x).replace(/\s+/g, " ").trim();
async function sha1hex(s) { const h = new Uint8Array(await crypto.subtle.digest("SHA-1", enc.encode(s))); return [...h].map((b) => b.toString(16).padStart(2, "0")).join(""); }
const ENT = { eacute: "é", egrave: "è", ecirc: "ê", euml: "ë", agrave: "à", acirc: "â", ccedil: "ç", icirc: "î", iuml: "ï", ocirc: "ô", ucirc: "û", ugrave: "ù", uuml: "ü", Eacute: "É", Agrave: "À", laquo: "«", raquo: "»", hellip: "…", rsquo: "’", lsquo: "‘", ndash: "–", mdash: "—", oelig: "œ", deg: "°", euro: "€" };
// Mêmes identifiants que build/infotrafic.py (sha1 de « titre|période », 10 caractères).
export async function parseTrafic(page) {
  const items = [];
  for (const m of page.matchAll(/<details[^>]*data-lines="([^"]*)"[^>]*>([\s\S]*?)<\/details>/gi)) {
    const inner = m[2], sm = /<summary[^>]*>([\s\S]*?)<\/summary>/i.exec(inner); if (!sm) continue;
    const title = textOf(sm[1].split(/<div/i)[0]);
    const h2 = /<h2[^>]*>([\s\S]*?)<\/h2>/i.exec(inner.slice(sm.index + sm[0].length));
    const period = h2 ? textOf(h2[1]) : "";
    const lines = [];
    for (let tok of m[1].split(",")) { tok = tok.trim().toUpperCase(); if (!tok) continue; for (const t of (ALIAS[tok] || tok).split(",")) if (!lines.includes(t)) lines.push(t); }
    items.push({ id: (await sha1hex(title + "|" + period)).slice(0, 10), t: title, lines });
  }
  return items;
}

// ---------- base ----------
async function authSub(env, b) {
  if (!b || !b.id || !b.key) return null;
  return env.DB.prepare("SELECT * FROM subs WHERE id = ? AND key = ?").bind(b.id, b.key).first();
}
async function dropSub(env, id) {
  await env.DB.batch([env.DB.prepare("DELETE FROM jobs WHERE sub = ?").bind(id), env.DB.prepare("DELETE FROM habits WHERE sub = ?").bind(id), env.DB.prepare("DELETE FROM subs WHERE id = ?").bind(id)]);
}
const clip = (s, n) => String(s == null ? "" : s).slice(0, n);
const cleanMsg = (j) => ({ title: clip(j.title, 80), body: clip(j.body, 240), url: clip(j.url || "./", 200), tag: clip(j.tag || "", 40) });

// ---------- adresses ----------
async function handle(req, env) {
  const url = new URL(req.url), path = url.pathname.replace(/\/+$/, "") || "/";
  if (req.method === "GET" && path === "/cle") return json({ key: (await vapid(env)).pub });
  if (req.method === "GET" && path === "/") return json({ ok: true, service: "alertes Horaires Grand Reims" });
  if (req.method !== "POST") return json({ error: "méthode" }, 405);
  const raw = await req.text(); if (raw.length > 200000) return json({ error: "trop gros" }, 413);
  let b; try { b = JSON.parse(raw); } catch { return json({ error: "json" }, 400); }
  const now = Date.now();

  if (path === "/abonner") {
    const s = b.sub; if (!s || !s.endpoint || !s.keys || !s.keys.p256dh || !s.keys.auth || !/^https:\/\//.test(s.endpoint)) return json({ error: "abonnement" }, 400);
    const old = await env.DB.prepare("SELECT id FROM subs WHERE endpoint = ?").bind(s.endpoint).first();
    if (old) await dropSub(env, old.id);
    const id = b64u(rand(12)), key = b64u(rand(18));
    await env.DB.prepare("INSERT INTO subs (id, key, endpoint, p256dh, auth, prefs, created, seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(id, key, s.endpoint, s.keys.p256dh, s.keys.auth, JSON.stringify(b.prefs || {}), now, now).run();
    return json({ id, key });
  }
  const sub = await authSub(env, b); if (!sub) return json({ error: "inconnu" }, 403);

  if (path === "/desabonner") { await dropSub(env, sub.id); return json({ ok: true }); }
  if (path === "/test") {
    const ok = await sendPush(env, sub, { title: "Les alertes marchent", body: "Vous recevrez vos alertes ici, même appli fermée.", url: "./", tag: "test" });
    if (!ok) await dropSub(env, sub.id);
    return json({ ok });
  }
  if (path === "/sync") {
    // réglages + envois programmés (dernier bus) + bus habituels des 7 jours à venir : tout est remplacé
    const st = [env.DB.prepare("UPDATE subs SET prefs = ?, seen = ? WHERE id = ?").bind(JSON.stringify(b.prefs || {}), now, sub.id),
      env.DB.prepare("DELETE FROM jobs WHERE sub = ? AND kind = 'last'").bind(sub.id),
      env.DB.prepare("DELETE FROM habits WHERE sub = ?").bind(sub.id)];
    for (const j of (b.jobs || []).slice(0, 40)) if (j.at > now && j.at < now + 8 * 864e5)
      st.push(env.DB.prepare("INSERT INTO jobs (sub, kind, at, msg) VALUES (?, 'last', ?, ?)").bind(sub.id, Math.round(j.at), JSON.stringify(cleanMsg(j))));
    for (const h of (b.habits || []).slice(0, 60)) {
      if (!h.trip || !Array.isArray(h.ids) || !Array.isArray(h.sched) || h.ids.length !== h.sched.length || !h.ids.length || h.ids.length > 120) continue;
      const at = h.sched[h.sched.length - 1] * 1000; if (at < now - 3600e3 || at > now + 8 * 864e5) continue;
      st.push(env.DB.prepare("INSERT INTO habits (sub, trip, at, data, sent) VALUES (?, ?, ?, ?, '')")
        .bind(sub.id, clip(h.trip, 80), at, JSON.stringify({ ids: h.ids.map((x) => clip(x, 40)), sched: h.sched.map(Number), min: Math.max(1, Math.min(30, +h.min || 10)), freq: ["steps", "min", "once"].includes(h.freq) ? h.freq : "steps", title: clip(h.title, 60), where: clip(h.where, 60), url: clip(h.url, 200) })));
    }
    await env.DB.batch(st);
    return json({ ok: true });
  }
  if (path === "/suivi") {
    const st = [env.DB.prepare("DELETE FROM jobs WHERE sub = ? AND kind = 'suivi'").bind(sub.id)];
    for (const j of (b.jobs || []).slice(0, 4)) if (j.at > now - 60000 && j.at < now + 6 * 3600e3)
      st.push(env.DB.prepare("INSERT INTO jobs (sub, kind, at, msg) VALUES (?, 'suivi', ?, ?)").bind(sub.id, Math.round(Math.max(j.at, now)), JSON.stringify(cleanMsg(j))));
    await env.DB.batch(st);
    return json({ ok: true });
  }
  if (path === "/annuler") { await env.DB.prepare("DELETE FROM jobs WHERE sub = ? AND kind = 'suivi'").bind(sub.id).run(); return json({ ok: true }); }
  return json({ error: "adresse" }, 404);
}

function cors(req, res) {
  const o = req.headers.get("Origin") || "";
  const ok = /^https:\/\/[a-z0-9-]+\.github\.io$/.test(o) || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(o);
  const h = new Headers(res.headers);
  if (ok) { h.set("Access-Control-Allow-Origin", o); h.set("Vary", "Origin"); h.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS"); h.set("Access-Control-Allow-Headers", "Content-Type"); h.set("Access-Control-Max-Age", "86400"); }
  return new Response(res.body, { status: res.status, headers: h });
}

// ---------- chaque minute ----------
function habitMsg(d, rem, est) {
  const late = est.live ? (est.delay > 0 ? ` · ${est.delay} min de retard` : est.delay < 0 ? " · en avance" : " · à l'heure") : "";
  if (rem <= 0.5) return { title: "Votre bus arrive", body: `${d.title} à ${d.where}`, url: d.url, tag: "hab" };
  return { title: `${d.title} dans ${Math.max(1, Math.round(rem))} min`, body: `${d.where}${late}`, url: d.url, tag: "hab" };
}
async function minute(env, now) {
  let sends = 0; const dead = new Set();
  const subCache = new Map(); const getSub = async (id) => { if (!subCache.has(id)) subCache.set(id, await env.DB.prepare("SELECT * FROM subs WHERE id = ?").bind(id).first()); return subCache.get(id); };
  const push = async (subId, m, topic) => {
    if (dead.has(subId)) return true; const s = await getSub(subId); if (!s) return true;
    sends++; try { if (!(await sendPush(env, s, m, topic))) dead.add(subId); } catch (e) { return false; }
    return true;
  };

  // 1. bus habituels dans leur fenêtre : temps réel, puis étapes
  const hs = (await env.DB.prepare("SELECT * FROM habits WHERE at BETWEEN ? AND ? ORDER BY at LIMIT 40").bind(now - 20 * 60000, now + 45 * 60000).all()).results || [];
  if (hs.length) {
    let trips = new Map();
    try { const r = await fetch(RT_URL, { cf: { cacheTtl: 20 } }); if (r.ok) trips = rtTrips(new Uint8Array(await r.arrayBuffer()), new Set(hs.map((h) => h.trip))); } catch (e) {}
    const upd = [];
    for (const h of hs) {
      if (sends >= MAX_SENDS) break;
      const d = JSON.parse(h.data), sent = new Set(h.sent ? h.sent.split(",") : []);
      const est = etaAt(trips.get(h.trip), d.ids, d.sched), rem = (est.eta * 1000 - now) / 60000;
      if (rem < -10 || (sent.has("arr") && rem < 0)) { upd.push(env.DB.prepare("DELETE FROM habits WHERE id = ?").bind(h.id)); continue; }
      if (rem > d.min + 0.5) continue;
      let step = null;
      if (rem <= 0.5) step = d.freq === "once" ? null : "arr";
      else if (d.freq === "once") step = "once";
      else if (d.freq === "min") step = "m" + Math.max(1, Math.round(rem));
      else { const T = [...new Set([d.min, 5, 2])].filter((x) => x <= d.min).sort((a, b) => a - b); const th = T.find((x) => rem <= x + 0.5); step = th != null ? "s" + th : null; }
      if (d.freq === "once" && rem <= 0.5 && !sent.has("once")) step = "once";
      if (!step || sent.has(step)) continue;
      // « par étapes » : une étape déjà passée ne repart pas (ex. abonné tard)
      if (step.startsWith("s")) for (const x of [...new Set([d.min, 5, 2])]) if (x >= +step.slice(1)) sent.add("s" + x);
      sent.add(step);
      const m = habitMsg(d, step === "arr" ? 0 : rem, est); m.tag = "hab" + h.id;
      if (await push(h.sub, m, "h" + h.id)) upd.push(env.DB.prepare("UPDATE habits SET sent = ? WHERE id = ?").bind([...sent].join(","), h.id));
    }
    if (upd.length) await env.DB.batch(upd);
  }

  // 2. envois programmés arrivés à échéance
  if (sends < MAX_SENDS) {
    const js = (await env.DB.prepare("SELECT * FROM jobs WHERE at <= ? ORDER BY at LIMIT ?").bind(now, MAX_SENDS - sends).all()).results || [];
    const del = [];
    for (const j of js) {
      if (now - j.at > 30 * 60000) { del.push(j.id); continue; } // trop vieux (service arrêté) : on laisse tomber
      const m = JSON.parse(j.msg);
      if (await push(j.sub, m, m.tag || ("j" + j.id))) del.push(j.id);
    }
    if (del.length) await env.DB.prepare(`DELETE FROM jobs WHERE id IN (${del.map(() => "?").join(",")})`).bind(...del).run();
  }
  for (const id of dead) await dropSub(env, id);
}

// ---------- toutes les 5 minutes : info trafic ----------
async function trafic(env, now) {
  let page;
  try { const r = await fetch(TRAFIC_URL, { headers: { "User-Agent": "Mozilla/5.0 (compatible; horaires-grand-reims-alertes; +" + CONTACT + ")", "Accept-Language": "fr" } }); if (!r.ok) return; page = await r.text(); } catch (e) { return; }
  const h = (await sha1hex(page.replace(/\s+/g, " ").replace(/name="[^"]*token[^"]*"\s+value="[^"]*"/gi, ""))).slice(0, 16);
  const last = await env.DB.prepare("SELECT v FROM kv WHERE k = 'trHash'").first();
  if (last && last.v === h) return;
  const items = await parseTrafic(page);
  const seenRow = await env.DB.prepare("SELECT v FROM kv WHERE k = 'trSeen'").first();
  const seen = new Set(seenRow ? JSON.parse(seenRow.v) : []);
  const fresh = seenRow ? items.filter((x) => !seen.has(x.id)) : []; // premier relevé : on note sans prévenir
  const st = [env.DB.prepare("INSERT OR REPLACE INTO kv (k, v) VALUES ('trHash', ?)").bind(h),
    env.DB.prepare("INSERT OR REPLACE INTO kv (k, v) VALUES ('trSeen', ?)").bind(JSON.stringify([...new Set([...items.map((x) => x.id), ...seen])].slice(-400)))];
  if (fresh.length && items.length) {
    const subs = (await env.DB.prepare("SELECT id, prefs FROM subs").all()).results || [];
    for (const s of subs) {
      const p = JSON.parse(s.prefs || "{}"); if (!p.trafic) continue;
      const mine = new Set(p.lines || []);
      const hit = fresh.filter((x) => p.scope === "all" || !x.lines.length || x.lines.some((l) => mine.has(l)));
      if (!hit.length) continue;
      const at = quietUntil(p, now) || now;
      const ls = [...new Set(hit.flatMap((x) => x.lines))];
      const m = hit.length === 1
        ? { title: "Info trafic" + (hit[0].lines.length ? " · " + hit[0].lines.slice(0, 4).join(", ") : " · tout le réseau"), body: hit[0].t, url: "./?o=tr:" + hit[0].id + "#trafic", tag: "tr" }
        : { title: `${hit.length} nouvelles infos trafic`, body: (ls.length ? "Lignes " + ls.slice(0, 6).join(", ") + " · " : "") + hit.map((x) => x.t).slice(0, 2).join(" · "), url: "./#trafic", tag: "tr" };
      st.push(env.DB.prepare("INSERT INTO jobs (sub, kind, at, msg) VALUES (?, 'trafic', ?, ?)").bind(s.id, at, JSON.stringify(m)));
    }
  }
  await env.DB.batch(st);
}

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") return cors(req, new Response(null, { status: 204 }));
    let res; try { res = await handle(req, env); } catch (e) { res = json({ error: "erreur", detail: String(e && e.message || e).slice(0, 200) }, 500); }
    return cors(req, res);
  },
  async scheduled(ev, env, ctx) {
    const now = ev.scheduledTime || Date.now();
    if (new Date(now).getUTCMinutes() % 5 === 0) await trafic(env, now).catch(() => {});
    await minute(env, Date.now());
    // ménage : abonnements jamais revus depuis 60 jours
    if (new Date(now).getUTCHours() === 3 && new Date(now).getUTCMinutes() === 7) {
      const old = (await env.DB.prepare("SELECT id FROM subs WHERE seen < ?").bind(now - 60 * 864e5).all()).results || [];
      for (const s of old) await dropSub(env, s.id);
    }
  },
};
