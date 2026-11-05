// Décodeur GTFS-RT minimal (protobuf) : TripUpdates et VehiclePositions.
function pbRead(buf) {
  let p = 0;
  const varint = () => {
    let r = 0, m = 1, b, n = 0; const st = p;
    do { b = buf[p++]; r += (b & 127) * m; m *= 128; n++; } while (b & 128);
    if (n < 8) return r;
    // grand varint (int64 négatif) : recalcul exact en BigInt
    let big = 0n, sh = 0n; for (let i = st; i < p; i++) { big |= BigInt(buf[i] & 127) << sh; sh += 7n; }
    return Number(BigInt.asIntN(64, big));
  };
  return {
    end: () => p >= buf.length,
    tag: () => { const t = varint(); return [Math.floor(t / 8), t & 7]; },
    varint,
    bytes: () => { const n = varint(); const s = buf.subarray(p, p + n); p += n; return s; },
    f32: () => { const v = new DataView(buf.buffer, buf.byteOffset + p, 4).getFloat32(0, true); p += 4; return v; },
    skip: (w) => { if (w === 0) varint(); else if (w === 1) p += 8; else if (w === 2) { const n = varint(); p += n; } else if (w === 5) p += 4; else throw new Error("wire " + w); },
  };
}
const td = new TextDecoder();
function rtMsg(buf, spec) {
  const r = pbRead(buf), o = {};
  while (!r.end()) {
    const [f, w] = r.tag(); const s = spec[f];
    if (!s) { r.skip(w); continue; }
    const [name, kind, sub, rep] = s;
    let v;
    if (kind === "s") v = td.decode(r.bytes());
    else if (kind === "m") v = rtMsg(r.bytes(), sub);
    else if (kind === "i") v = r.varint();
    else if (kind === "f") v = r.f32();
    else { r.skip(w); continue; }
    if (rep) (o[name] = o[name] || []).push(v); else o[name] = v;
  }
  return o;
}
const RT_TD = { 1: ["trip_id", "s"], 2: ["start_time", "s"], 3: ["start_date", "s"], 4: ["rel", "i"], 5: ["route_id", "s"], 6: ["direction_id", "i"] };
const RT_EV = { 1: ["delay", "i"], 2: ["time", "i"] };
const RT_STU = { 1: ["seq", "i"], 2: ["arr", "m", RT_EV], 3: ["dep", "m", RT_EV], 4: ["stop_id", "s"], 5: ["rel", "i"] };
const RT_VD = { 1: ["id", "s"], 2: ["label", "s"] };
const RT_TU = { 1: ["trip", "m", RT_TD], 3: ["vehicle", "m", RT_VD], 2: ["stu", "m", RT_STU, 1], 4: ["ts", "i"], 5: ["delay", "i"] };
const RT_POS = { 1: ["lat", "f"], 2: ["lon", "f"], 3: ["bearing", "f"] };
const RT_VP = { 1: ["trip", "m", RT_TD], 2: ["pos", "m", RT_POS], 3: ["seq", "i"], 4: ["status", "i"], 5: ["ts", "i"], 7: ["stop_id", "s"], 8: ["vehicle", "m", RT_VD] };
const RT_ENT = { 1: ["id", "s"], 2: ["deleted", "i"], 3: ["tu", "m", RT_TU], 4: ["vp", "m", RT_VP] };
const RT_HDR = { 1: ["version", "s"], 2: ["inc", "i"], 3: ["ts", "i"] };
const RT_FEED = { 1: ["header", "m", RT_HDR], 2: ["entity", "m", RT_ENT, 1] };
function decodeFeed(u8) {
  return rtMsg(u8, RT_FEED);
}
if (typeof module !== "undefined") module.exports = { decodeFeed };
