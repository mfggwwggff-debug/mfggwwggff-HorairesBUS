// Essais hors ligne : node notifs/test.mjs (vecteur de la RFC 8291, lecture GTFS-RT, info trafic)
import { encryptPush, rtTrips, etaAt, parseTrafic } from "./worker.js";
import fs from "node:fs";
const u = (s) => { s = s.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "="; return Uint8Array.from(atob(s), (c) => c.charCodeAt(0)); };
const b = (a) => Buffer.from(a).toString("base64url");
// RFC 8291, annexe A
const asPub = u("BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8");
const jwk = { kty: "EC", crv: "P-256", d: "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw", x: b(asPub.slice(1, 33)), y: b(asPub.slice(33)), ext: true };
const privateKey = await crypto.subtle.importKey("jwk", jwk, { name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
const publicKey = await crypto.subtle.importKey("raw", asPub, { name: "ECDH", namedCurve: "P-256" }, true, []);
const out = await encryptPush("When I grow up, I want to be a watermelon", "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4", "BTBZMqHH6r4Tts7J_aSIgg", { privateKey, publicKey }, u("DGv6ra1nlYgDCS1FRnbzlw"));
const want = "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN";
console.log("RFC 8291 :", b(out) === want ? "OK" : "DIFFÉRENT\n" + b(out));
// GTFS-RT : flux enregistré si présent
if (process.argv[2]) {
  const buf = new Uint8Array(fs.readFileSync(process.argv[2]));
  const t0 = performance.now(); const m = rtTrips(buf, new Set([process.argv[3] || "x"])); console.log("GTFS-RT :", buf.length, "octets,", (performance.now() - t0).toFixed(2), "ms,", m.size, "course(s)");
}
console.log("etaAt :", JSON.stringify(etaAt([{ stop_id: "B", dep: { delay: 180 } }], ["A", "B", "C"], [1000, 1100, 1200])), JSON.stringify(etaAt([], ["A"], [1000])));
if (process.argv[4]) { const page = fs.readFileSync(process.argv[4], "utf8"); const t0 = performance.now(); const it = await parseTrafic(page); console.log("trafic :", it.length, "infos,", (performance.now() - t0).toFixed(1), "ms", JSON.stringify(it.slice(0, 2))); }
