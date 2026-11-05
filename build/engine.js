// Moteur horaires + calcul d'itinéraire (RAPTOR) pour un GTFS compacté, avec surcouche temps réel.
function makeNet(D) {
  const net = { D, P: D.P, Q: D.Q, R: D.R, nQ: D.Q.length };
  const y = +D.d0.slice(0, 4), m = +D.d0.slice(4, 6) - 1, d = +D.d0.slice(6, 8);
  net.day0 = Date.UTC(y, m, d);
  net.nd = D.nd;
  net.dayIndex = (iso) => { const [a, b, c] = iso.split("-").map(Number); return Math.round((Date.UTC(a, b - 1, c) - net.day0) / 864e5); };
  net.isoOf = (k) => new Date(net.day0 + k * 864e5).toISOString().slice(0, 10);
  net.svcOn = (sv, k) => k >= 0 && k < net.nd && D.S[sv].charCodeAt(k) === 49;
  net.pats = D.PAT.map(([r, dir, h, sh, stops, trs]) => {
    const nS = stops.length, nT = trs.length;
    const A = new Int32Array(nT * nS), Dp = new Int32Array(nT * nS), sv = new Int32Array(nT);
    trs.forEach((t, k) => {
      sv[k] = t[0];
      const two = t[1] === 1;
      let acc = 0, j = 2;
      for (let i = 0; i < nS; i++) {
        acc += t[j++]; const a = acc; let dd = a;
        if (two) { acc += t[j++]; dd = acc; }
        A[k * nS + i] = a; Dp[k * nS + i] = dd;
      }
    });
    return { r, dir, h, sh, stops, nS, nT, A, D: Dp, sv, LA: null, LD: null, live: null };
  });
  net.qp = Array.from({ length: net.nQ }, () => []);
  net.pats.forEach((p, pi) => p.stops.forEach((q, i) => net.qp[q].push(pi, i)));
  net.fp = D.FP;
  net.pRoutes = net.P.map((p) => {
    const s = new Set();
    p[3].forEach((q) => { const l = net.qp[q]; for (let i = 0; i < l.length; i += 2) s.add(net.pats[l[i]].r); });
    return [...s].sort((a, b) => a - b);
  });
  net.shapes = D.SH.map((f) => { const o = []; let x = 0, yy = 0; for (let i = 0; i < f.length; i += 2) { x += f[i]; yy += f[i + 1]; o.push([x / 1e5, yy / 1e5]); } return o; });
  // identifiants pour le temps réel
  net.tripIdx = new Map();
  if (D.TI) D.TI.t.forEach((row, pi) => row.split(" ").forEach((code, k) => { const [num, s] = code.split("."); const suf = D.TI.suf[+s]; net.tripIdx.set(num ? num + "-" + suf : suf, [pi, k]); }));
  net.qByStopId = new Map((D.QI || []).map((sid, q) => [sid, q]));
  net.liveDay = -1;
  return net;
}

// Horaires à utiliser pour un jour de service donné (temps réel si disponible)
function arr(net, p, svcDay) { return svcDay === net.liveDay && p.LA ? [p.LA, p.LD] : [p.A, p.D]; }
function isLive(net, p, k, svcDay) { return svcDay === net.liveDay && p.live && p.live[k] === 1; }

// Applique un flux GTFS-RT décodé. dayStartEpoch(k) = epoch (s) de minuit du jour de service k.
function applyRT(net, feed, liveDay, dayStartEpoch) {
  net.pats.forEach((p) => { p.LA = null; p.LD = null; p.live = null; });
  net.liveDay = liveDay;
  let matched = 0, total = 0;
  for (const e of feed.entity || []) {
    const tu = e.tu; if (!tu || !tu.trip || e.deleted) continue;
    total++;
    const hit = net.tripIdx.get(tu.trip.trip_id); if (!hit) continue;
    const [pi, k] = hit, p = net.pats[pi];
    // jour de service : aujourd'hui, ou la veille pour une course d'après minuit
    let svc = liveDay;
    if (tu.trip.start_date) svc = net.dayIndex(tu.trip.start_date.slice(0, 4) + "-" + tu.trip.start_date.slice(4, 6) + "-" + tu.trip.start_date.slice(6, 8));
    else if (!net.svcOn(p.sv[k], liveDay) && net.svcOn(p.sv[k], liveDay - 1)) svc = liveDay - 1;
    if (!net.svcOn(p.sv[k], svc)) continue;
    const off = (svc - liveDay) * 1440; // -1440 pour la veille
    if (off !== 0) continue; // les courses de la veille restent théoriques (rare : après minuit)
    const base = dayStartEpoch(svc);
    const upd = new Map();
    for (const s of tu.stu || []) {
      let i = -1;
      if (s.stop_id && net.qByStopId.has(s.stop_id)) { const q = net.qByStopId.get(s.stop_id); i = p.stops.indexOf(q); }
      if (i < 0 && s.seq) i = s.seq - 1;
      if (i < 0 || i >= p.nS) continue;
      const ev = (x, sched) => !x ? null : (x.time ? Math.round((x.time - base) / 60) : (x.delay !== undefined ? sched + Math.round(x.delay / 60) : null));
      const a = ev(s.arr, p.A[k * p.nS + i]), d = ev(s.dep, p.D[k * p.nS + i]);
      if (a == null && d == null) continue;
      upd.set(i, [a ?? d, d ?? a]);
    }
    if (!upd.size) continue;
    if (!p.LA) { p.LA = Int32Array.from(p.A); p.LD = Int32Array.from(p.D); p.live = new Uint8Array(p.nT); }
    const first = Math.min(...upd.keys());
    // arrêts sans prévision : un seul retard propagé (celui du départ du dernier arrêt connu),
    // sinon un écart arrivée/départ à un arrêt de régulation se recopiait en attente fictive à chaque arrêt
    let delay = upd.get(first)[0] - p.A[k * p.nS + first];
    let prev = -Infinity;
    for (let i = 0; i < p.nS; i++) {
      const o = k * p.nS + i;
      let a, d;
      if (upd.has(i)) { [a, d] = upd.get(i); delay = d - p.D[o]; }
      else { a = p.A[o] + delay; d = p.D[o] + delay; }
      if (a < prev) a = prev; if (d < a) d = a; prev = d;
      p.LA[o] = a; p.LD[o] = d;
    }
    p.live[k] = 1; matched++;
  }
  return { matched, total };
}

function firstTrip(net, p, i, ready, day) {
  let best = null;
  for (const off of [0, -1440]) {
    const dk = off === 0 ? day : day - 1;
    const [, DD] = arr(net, p, dk);
    for (let k = 0; k < p.nT; k++) {
      const t = DD[k * p.nS + i] + off;
      if (t >= ready && (!best || t < best.t) && net.svcOn(p.sv[k], dk)) best = { k, off, t, dk };
    }
  }
  if (best) [best.A, best.D] = arr(net, p, best.dk);
  return best;
}

function raptor(net, o, dst, day, t0, maxRides = 5) {
  const nQ = net.nQ, INF = 1e9;
  const dstQ = new Set(net.P[dst][3]);
  const tau = [], lab = [];
  const best = new Int32Array(nQ).fill(INF);
  const newRound = () => { const t = new Int32Array(nQ).fill(INF); tau.push(t); const l = { ty: new Int8Array(nQ), a: new Int32Array(nQ), b: new Int32Array(nQ), c: new Int32Array(nQ), d: new Int32Array(nQ), e: new Int32Array(nQ) }; lab.push(l); return [t, l]; };
  let [t, l] = newRound();
  let marked = new Set();
  for (const q of net.P[o][3]) { t[q] = t0; best[q] = t0; l.ty[q] = 1; marked.add(q); }
  const relax = (k, from) => {
    const T = tau[k], L = lab[k], add = [];
    for (const q of from) {
      if (!(L.ty[q] === 1 || L.ty[q] === 2)) continue;
      const f = net.fp[q];
      for (let j = 0; j < f.length; j += 2) {
        const q2 = f[j], v = T[q] + f[j + 1];
        if (v < T[q2] && v < best[q2]) { T[q2] = v; best[q2] = v; L.ty[q2] = 3; L.a[q2] = q; L.b[q2] = f[j + 1]; add.push(q2); }
      }
    }
    add.forEach((q) => from.add(q));
  };
  relax(0, marked);
  const destBest = () => { let m = INF; dstQ.forEach((q) => { if (best[q] < m) m = best[q]; }); return m; };
  for (let k = 1; k <= maxRides && marked.size; k++) {
    const prevT = tau[k - 1], prevL = lab[k - 1];
    [t, l] = newRound();
    const Qp = new Map();
    for (const q of marked) {
      const lst = net.qp[q];
      for (let x = 0; x < lst.length; x += 2) { const pi = lst[x], i = lst[x + 1]; const c = Qp.get(pi); if (c === undefined || i < c) Qp.set(pi, i); }
    }
    const nm = new Set();
    for (const [pi, i0] of Qp) {
      const p = net.pats[pi];
      let cur = null, bi = -1;
      for (let i = i0; i < p.nS; i++) {
        const q = p.stops[i];
        if (cur && i > 0) {
          const a = cur.A[cur.k * p.nS + i] + cur.off;
          if (a < best[q] && a < destBest()) {
            t[q] = a; best[q] = a; l.ty[q] = 2; l.a[q] = pi; l.b[q] = cur.k; l.c[q] = cur.off; l.d[q] = bi; l.e[q] = i; nm.add(q);
          }
        }
        if (i < p.nS - 1 && prevT[q] < INF) {
          const ready = prevT[q] + (prevL.ty[q] === 2 ? 1 : 0);
          const curDep = cur ? cur.D[cur.k * p.nS + i] + cur.off : INF;
          if (ready <= curDep) {
            const ft = firstTrip(net, p, i, ready, day);
            if (ft && ft.t < curDep) { cur = ft; bi = i; }
          }
        }
      }
    }
    relax(k, nm);
    marked = nm;
  }
  const res = [];
  let prevBest = INF;
  for (let k = 1; k < tau.length; k++) {
    let bq = -1, bv = INF;
    dstQ.forEach((q) => { if (tau[k][q] < bv) { bv = tau[k][q]; bq = q; } });
    if (bv < prevBest) { prevBest = bv; res.push(rebuild(net, tau, lab, k, bq, day)); }
  }
  return res;
}

function rebuild(net, tau, lab, k, q, day) {
  const legs = [];
  while (k >= 0) {
    const L = lab[k];
    const ty = L.ty[q];
    if (ty === 1) break;
    if (ty === 3) { legs.push({ type: "walk", from: L.a[q], to: q, dur: L.b[q], arr: tau[k][q] }); q = L.a[q]; continue; }
    if (ty === 2) {
      const p = net.pats[L.a[q]];
      const kk = L.b[q], off = L.c[q], bi = L.d[q], ai = L.e[q];
      const sd = off === 0 ? day : day - 1;
      const [A, Dd] = arr(net, p, sd);
      legs.push({ type: "ride", pat: L.a[q], trip: kk, off, bi, ai, svcDay: sd, live: isLive(net, p, kk, sd),
        dep: Dd[kk * p.nS + bi] + off, arr: A[kk * p.nS + ai] + off,
        sdep: p.D[kk * p.nS + bi] + off, sarr: p.A[kk * p.nS + ai] + off });
      q = p.stops[bi]; k -= 1; continue;
    }
    break;
  }
  legs.reverse();
  for (let i = 0; i < legs.length; i++) {
    const g = legs[i];
    if (g.type !== "walk") continue;
    const nxt = legs.slice(i + 1).find((x) => x.type === "ride");
    const prv = legs.slice(0, i).reverse().find((x) => x.type === "ride");
    if (!prv && nxt) { g.arr = nxt.dep; g.dep = g.arr - g.dur; }
    else { g.dep = (prv ? prv.arr : g.arr - g.dur); g.arr = g.dep + g.dur; }
  }
  const rides = legs.filter((x) => x.type === "ride");
  const dep = legs.length ? legs[0].dep : 0, arrv = legs.length ? legs[legs.length - 1].arr : 0;
  return { legs, dep, arr: arrv, rides: rides.length, live: rides.some((r) => r.live), key: rides.map((r) => r.pat + ":" + r.trip + ":" + r.bi + ":" + r.ai).join("|") };
}

function planDepart(net, o, dst, day, t0, want = 4) {
  const out = new Map();
  let t = t0;
  for (let it = 0; it < 12 && out.size < want; it++) {
    const res = raptor(net, o, dst, day, t);
    if (!res.length) break;
    res.forEach((j) => { if (!out.has(j.key) && j.legs.length) out.set(j.key, j); });
    const firstRide = Math.min(...res.map((j) => (j.legs.find((x) => x.type === "ride") || { dep: t }).dep));
    t = Math.max(t + 1, firstRide - (res[0].legs[0].type === "walk" ? res[0].legs[0].dur : 0) + 1);
  }
  return prune([...out.values()]).slice(0, want + 1);
}

function planArrive(net, o, dst, day, deadline, want = 3) {
  const out = new Map();
  for (let back = 15; back <= 240 && out.size < want + 2; back += 10) {
    const res = raptor(net, o, dst, day, deadline - back);
    res.forEach((j) => { if (j.arr <= deadline && j.legs.length && !out.has(j.key)) out.set(j.key, j); });
  }
  const sols = prune([...out.values()]).filter((j) => j.arr <= deadline);
  sols.sort((a, b) => b.dep - a.dep);
  return sols.slice(0, want).sort((a, b) => a.dep - b.dep);
}

function prune(list) {
  const dom = (b, a) => b !== a && (
    (b.dep >= a.dep && b.arr <= a.arr && b.rides <= a.rides && (b.dep > a.dep || b.arr < a.arr || b.rides < a.rides)) ||
    (b.rides < a.rides && b.dep >= a.dep - 5 && b.arr <= a.arr + 5 && (b.arr - b.dep) <= (a.arr - a.dep) + 5));
  const keep = list.filter((a) => !list.some((b) => dom(b, a)));
  keep.sort((a, b) => a.dep - b.dep || a.arr - b.arr);
  return keep;
}

function departures(net, pStop, day, t0, horizon = 120) {
  const rows = [];
  for (const q of net.P[pStop][3]) {
    const lst = net.qp[q];
    for (let x = 0; x < lst.length; x += 2) {
      const p = net.pats[lst[x]], i = lst[x + 1];
      if (i === p.nS - 1) continue;
      for (const off of [0, -1440]) {
        const dk = off === 0 ? day : day - 1;
        const [, DD] = arr(net, p, dk);
        for (let k = 0; k < p.nT; k++) {
          const tt = DD[k * p.nS + i] + off;
          if (tt >= t0 && tt <= t0 + horizon && net.svcOn(p.sv[k], dk)) rows.push({ t: tt, st: p.D[k * p.nS + i] + off, live: isLive(net, p, k, dk), pat: lst[x], k, i, off, q });
        }
      }
    }
  }
  rows.sort((a, b) => a.t - b.t);
  return rows;
}

if (typeof module !== "undefined") module.exports = { makeNet, raptor, planDepart, planArrive, departures, firstTrip, applyRT, arr, isLive };
