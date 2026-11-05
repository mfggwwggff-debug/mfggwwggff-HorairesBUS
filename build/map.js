// ---------- Plan du réseau (canvas) ----------
const cv = $("#map"), ctx = cv.getContext("2d");
// Projection de Mercator (celle des fonds de carte), mise à l'échelle pour qu'une unité vaille
// un degré de latitude autour de Reims : 111 320 m par unité, comme avant.
const KX = Math.cos(49.25 * Math.PI / 180), DEG = 180 / Math.PI;
const PX = (lon) => lon * KX, PY = (lat) => Math.log(Math.tan(Math.PI / 4 + lat / 2 / DEG)) * DEG * KX;
const IX = (x) => x / KX, IY = (y) => (2 * Math.atan(Math.exp(y / KX / DEG)) - Math.PI / 2) * DEG;
const view = { cx: PX(4.03), cy: PY(49.255), s: 9000 };
const ZMIN = 1500, ZMAX = 120000;
let W = 0, H = 0, DPR = 1;
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const toS = (x, y) => [(x - view.cx) * view.s + W / 2, H / 2 - (y - view.cy) * view.s];
const fromS = (sx, sy) => [(sx - W / 2) / view.s + view.cx, view.cy - (sy - H / 2) / view.s];
const geoS = (lon, lat) => toS(PX(lon), PY(lat));
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const topInset = () => isMobile() ? (parseFloat(css("--sat")) || 0) + 8 : 0;

// tracés : un par motif distinct
const shapeOfPat = net.pats.map((p) => p.sh >= 0 ? net.shapes[p.sh] : p.stops.map((q) => [net.Q[q][2], net.Q[q][1]]));
const routeShapes = net.R.map(() => new Set());
const shapeKey = (i) => net.pats[i].sh >= 0 ? "s" + net.pats[i].sh : "p" + i;
net.pats.forEach((p, i) => routeShapes[p.r].add(shapeKey(i)));
const keyToPts = new Map(); net.pats.forEach((p, i) => keyToPts.set(shapeKey(i), shapeOfPat[i]));
const hubs = new Set(net.P.map((p, i) => i).filter((i) => net.pRoutes[i].length >= 3));

// géométrie des motifs : tracé projeté, distances cumulées, position de chaque arrêt sur le tracé
const geoCache = new Map();
function patGeo(pi) {
  if (geoCache.has(pi)) return geoCache.get(pi);
  const p = net.pats[pi], pts = shapeOfPat[pi].map(([lo, la]) => [PX(lo), PY(la)]);
  const cum = [0]; for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const sOff = []; let from = 0;
  for (const q of p.stops) {
    const x = PX(net.Q[q][2]), y = PY(net.Q[q][1]);
    let best = Infinity, bd = cum[from] || 0, bseg = from;
    const lim = Math.min(pts.length - 1, from + 400);
    for (let i = from; i < lim; i++) {
      const [ax, ay] = pts[i], [bx, by] = pts[i + 1], dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1e-18;
      const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / L2));
      const d = (ax + t * dx - x) ** 2 + (ay + t * dy - y) ** 2;
      if (d < best - 1e-14) { best = d; bd = cum[i] + t * Math.sqrt(L2); bseg = i; }
    }
    if (pts.length < 2) bd = 0;
    sOff.push(Math.max(bd, sOff.length ? sOff[sOff.length - 1] : 0)); from = bseg;
  }
  const g = { pts, cum, sOff };
  geoCache.set(pi, g); return g;
}
function pointAt(g, d) {
  const { pts, cum } = g;
  if (pts.length < 2) return [pts[0][0], pts[0][1], 0];
  let lo = 0, hi = cum.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cum[m] <= d) lo = m; else hi = m; }
  const L = cum[hi] - cum[lo] || 1e-12, t = Math.max(0, Math.min(1, (d - cum[lo]) / L));
  return [pts[lo][0] + t * (pts[hi][0] - pts[lo][0]), pts[lo][1] + t * (pts[hi][1] - pts[lo][1]), Math.atan2(pts[hi][1] - pts[lo][1], pts[hi][0] - pts[lo][0])];
}

// ---------- véhicules : position estimée ----------
// Entre deux arrêts, le bus avance le long du tracé au prorata du temps écoulé entre le départ du
// précédent et l'arrivée au suivant. Horaires temps réel si la course est suivie, théoriques sinon.
let showBuses = store.get("buses") !== false;
function posOf(pi, k, dk, t, today) {
  const p = net.pats[pi], off = (dk - today) * 1440, o = k * p.nS;
  const [A, D] = arr(net, p, dk);
  if (t < D[o] + off || t > A[o + p.nS - 1] + off) return null;
  let i = 0; while (i < p.nS - 1 && A[o + i + 1] + off <= t) i++;
  const g = patGeo(pi);
  let d, nextI, atStop = false;
  const ai = A[o + i] + off, di = D[o + i] + off;
  if (t >= ai && t <= di) { d = g.sOff[i]; nextI = i; atStop = true; }
  else if (i >= p.nS - 1) { d = g.sOff[p.nS - 1]; nextI = p.nS - 1; atStop = true; }
  else { const t0 = di, t1 = A[o + i + 1] + off, f = t1 > t0 ? (t - t0) / (t1 - t0) : 1; d = g.sOff[i] + Math.max(0, Math.min(1, f)) * (g.sOff[i + 1] - g.sOff[i]); nextI = i + 1; }
  const [x, y, ang] = pointAt(g, d);
  const live = isLive(net, p, k, dk);
  return { pi, k, dk, x, y, ang, live, nextI, atStop, next: A[o + nextI] + off, delay: live ? Math.round(A[o + nextI] - p.A[o + nextI]) : 0, r: p.r };
}
function vehicles() {
  const today = todayIdx(), t = nowMinF();
  if (today < 0 || today > net.nd) return [];
  const out = [];
  net.pats.forEach((p, pi) => {
    for (const dk of [today, today - 1]) {
      if (dk < 0 || dk >= net.nd) continue;
      for (let k = 0; k < p.nT; k++) {
        if (!net.svcOn(p.sv[k], dk)) continue;
        const v = posOf(pi, k, dk, t, today); if (v) out.push(v);
      }
    }
  });
  return out;
}
const vehicleOf = (pi, k, dk) => posOf(pi, k, dk, nowMinF(), todayIdx());

function resize() {
  const r = cv.getBoundingClientRect(); DPR = window.devicePixelRatio || 1; W = r.width; H = r.height;
  cv.width = tcv.width = Math.round(W * DPR); cv.height = tcv.height = Math.round(H * DPR); paint();
}
function path(pts) { ctx.beginPath(); for (let i = 0; i < pts.length; i++) { const [x, y] = geoS(pts[i][0], pts[i][1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); } }
function segment(pi, bi, ai) {
  const g = patGeo(pi), a = g.sOff[bi], b = g.sOff[ai], out = [];
  const pa = pointAt(g, a); out.push([IX(pa[0]), IY(pa[1])]);
  for (let i = 0; i < g.pts.length; i++) if (g.cum[i] > a && g.cum[i] < b) out.push([IX(g.pts[i][0]), IY(g.pts[i][1])]);
  const pb = pointAt(g, b); out.push([IX(pb[0]), IY(pb[1])]);
  return out;
}
function segmentD(pi, a, b) {
  const g = patGeo(pi), out = [];
  const pa = pointAt(g, a); out.push([IX(pa[0]), IY(pa[1])]);
  for (let i = 0; i < g.pts.length; i++) if (g.cum[i] > a && g.cum[i] < b) out.push([IX(g.pts[i][0]), IY(g.pts[i][1])]);
  const pb = pointAt(g, b); out.push([IX(pb[0]), IY(pb[1])]);
  return out;
}
function highlight() {
  const H = { routes: null, legs: [], stops: [], ends: [], trips: null };
  if (S.view === "itineraire") {
    const j = S.journeys[S.selJ];
    if (j) {
      H.routes = new Set(); H.trips = new Set();
      j.legs.forEach((g) => {
        if (g.type === "ride") {
          const p = net.pats[g.pat];
          H.legs.push({ pts: segment(g.pat, g.bi, g.ai), c: net.R[p.r].c });
          H.routes.add(p.r); H.trips.add(g.pat + ":" + g.trip);
          for (let s = g.bi; s <= g.ai; s++) H.stops.push(net.Q[p.stops[s]][0]);
        } else {
          const a = net.Q[g.from], b = net.Q[g.to];
          H.legs.push({ pts: [[a[2], a[1]], [b[2], b[1]]], walk: true });
        }
      });
    }
    if (S.from != null) H.ends.push([S.from, "from"]);
    if (S.to != null) H.ends.push([S.to, "to"]);
  } else if (S.view === "passages" && S.paStop != null) {
    H.routes = new Set(net.pRoutes[S.paStop]); H.ends.push([S.paStop, "from"]);
  } else if (S.view === "lignes" && S.line != null) {
    H.routes = new Set([S.line]);
    net.pats.forEach((p) => { if (p.r === S.line) p.stops.forEach((q) => H.stops.push(net.Q[q][0])); });
  } else if (S.view === "suivi" && S.follow) {
    const { pi, k, dk, dest } = S.follow, p = net.pats[pi], g = patGeo(pi);
    H.routes = new Set([p.r]); H.trips = new Set([pi + ":" + k]);
    const v = vehicleOf(pi, k, dk);
    const st = tripState(pi, k, dk);
    let cut = st.state === "before" ? 0 : st.state === "done" ? g.sOff[p.nS - 1] : 0;
    if (v) { const gg = patGeo(pi); let best = 0, bd = Infinity; for (let i = 0; i < gg.pts.length; i++) { const d = (gg.pts[i][0] - v.x) ** 2 + (gg.pts[i][1] - v.y) ** 2; if (d < bd) { bd = d; best = gg.cum[i]; } } cut = best; }
    const end = dest != null ? g.sOff[dest] : g.sOff[p.nS - 1];
    if (cut > 0) H.legs.push({ pts: segmentD(pi, 0, cut), c: net.R[p.r].c, faded: true });
    if (end > cut) H.legs.push({ pts: segmentD(pi, cut, end), c: net.R[p.r].c });
    if (dest != null && dest < p.nS - 1) H.legs.push({ pts: segmentD(pi, end, g.sOff[p.nS - 1]), c: net.R[p.r].c, faded: true });
    p.stops.forEach((q) => H.stops.push(net.Q[q][0]));
    if (dest != null) H.ends.push([net.Q[p.stops[dest]][0], "to"]);
  } else if (S.view === "trafic" && TR.filter) {
    H.routes = new Set(TR.filter);
  } else if (S.view === "accueil") {
    if (ME.pos) nearestStops(4, 1000).forEach((x) => H.stops.push(x.i));
    fav.stops.map(findStop).filter((i) => i >= 0).forEach((i) => H.stops.push(i));
  }
  return H;
}

// ---------- tronçons communs dessinés en parallèle ----------
// Données préparées par build/post.py : par ligne, des tronçons de tracé et, en chaque point, une place
// dans le faisceau (slot). On décale chaque point de slot × écartement, perpendiculairement au tracé.
const LN = (net.D.LN || []).map(([r, c, sl]) => {
  const xs = [], ys = []; let x = 0, y = 0, x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < c.length; i += 2) { x += c[i]; y += c[i + 1]; const X = PX(x / 1e5), Y = PY(y / 1e5); xs.push(X); ys.push(Y); x0 = Math.min(x0, X); x1 = Math.max(x1, X); y0 = Math.min(y0, Y); y1 = Math.max(y1, Y); }
  return { r, xs, ys, sl: sl.map((v) => v / 4), box: [x0, y0, x1, y1] };
});
const lnByRoute = net.R.map(() => []); LN.forEach((f) => lnByRoute[f.r].push(f));
function offsetPath(f, sp) {
  const n = f.xs.length, P = new Array(n);
  for (let i = 0; i < n; i++) P[i] = toS(f.xs[i], f.ys[i]);
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const a = P[Math.max(0, i - 1)], b = P[i], c = P[Math.min(n - 1, i + 1)];
    let n1x = 0, n1y = 0, n2x = 0, n2y = 0;
    const d1 = Math.hypot(b[0] - a[0], b[1] - a[1]), d2 = Math.hypot(c[0] - b[0], c[1] - b[1]);
    if (d1 > 1e-6) { n1x = -(b[1] - a[1]) / d1; n1y = (b[0] - a[0]) / d1; }
    if (d2 > 1e-6) { n2x = -(c[1] - b[1]) / d2; n2y = (c[0] - b[0]) / d2; }
    if (!d1) { n1x = n2x; n1y = n2y; } if (!d2) { n2x = n1x; n2y = n1y; }
    let mx = n1x + n2x, my = n1y + n2y; const ml = Math.hypot(mx, my) || 1; mx /= ml; my /= ml;
    const k = f.sl[i] * sp / Math.max(0.55, mx * n2x + my * n2y);
    const X = b[0] - mx * k, Y = b[1] - my * k;
    i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y);
  }
}

// ---------- fond de carte (rues) ----------
// Tuiles OpenStreetMap dessinées dans un calque à part (#tiles), adouci par un filtre CSS : gris clair
// le jour, inversé la nuit. Pas sur claude.ai, qui bloque les images externes.
const TILES_OK = !/claude/.test(location.hostname);
const tcv = $("#tiles"), tctx = tcv.getContext("2d");
const tileCache = new Map(); let tilesLoading = 0;
const isDark = () => { const t = document.documentElement.dataset.theme; return t === "dark" || (t !== "light" && matchMedia("(prefers-color-scheme: dark)").matches); };
function tileImg(z, x, y) {
  const key = z + "/" + x + "/" + y;
  let e = tileCache.get(key);
  if (!e) {
    if (tilesLoading > 24) return null;
    const img = new Image(); e = { img, ok: false, t: 0 };
    img.onload = () => { e.ok = true; tilesLoading--; drawMap(); };
    img.onerror = () => { e.err = true; tilesLoading--; };
    tilesLoading++;
    img.src = `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
    tileCache.set(key, e);
    if (tileCache.size > 400) { for (const [k, v] of tileCache) { if (v.ok || v.err) { tileCache.delete(k); if (tileCache.size <= 320) break; } } }
  }
  e.t = performance.now();
  return e.ok ? e.img : null;
}
function drawTiles(bg) {
  const ctx = tctx;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
  const dark = isDark(), f = dark ? "grayscale(1) invert(1) brightness(.78) contrast(.92)" : "grayscale(1) brightness(1.05) contrast(.82)";
  if (tcv.style.filter !== f) { tcv.style.filter = f; tcv.style.opacity = dark ? ".75" : ".85"; }
  const zf = Math.log2(view.s * 360 * KX / 256) + (DPR > 1 ? 0.45 : 0);
  const z = Math.max(9, Math.min(19, Math.round(zf))), N = 2 ** z;
  const tx = (X) => (IX(X) + 180) / 360 * N, ty = (Y) => (1 - Y / (180 * KX)) / 2 * N;
  const [ax, ay] = fromS(0, 0), [bx, by] = fromS(W, H);
  const x0 = Math.floor(tx(ax)), x1 = Math.floor(tx(bx)), y0 = Math.floor(ty(ay)), y1 = Math.floor(ty(by));
  const sx = (i) => toS(PX(i / N * 360 - 180), 0)[0], sy = (j) => toS(0, (1 - 2 * j / N) * 180 * KX)[1];
  ctx.imageSmoothingQuality = "high";
  for (let j = y0; j <= y1; j++) for (let i = x0; i <= x1; i++) {
    if (j < 0 || j >= N) continue;
    const X0 = sx(i), X1 = sx(i + 1), Y0 = sy(j), Y1 = sy(j + 1);
    const img = tileImg(z, ((i % N) + N) % N, j);
    if (img) { ctx.drawImage(img, X0, Y0, X1 - X0 + 0.5, Y1 - Y0 + 0.5); continue; }
    // en attendant : la tuile parente déjà chargée, agrandie
    for (let up = 1; up <= 4; up++) {
      const pz = z - up, pi = i >> up, pj = j >> up, k = 1 << up;
      const e = tileCache.get(pz + "/" + pi + "/" + pj);
      if (e && e.ok) { const w = e.img.naturalWidth / k, h = e.img.naturalHeight / k; ctx.drawImage(e.img, (i - pi * k) * w, (j - pj * k) * h, w, h, X0, Y0, X1 - X0 + 0.5, Y1 - Y0 + 0.5); break; }
    }
  }
}

let raf = 0, hover = null, lastVeh = [];
function drawMap() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; paint(); }); }
function roundRect(x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
function paint() {
  if (!W) return;
  // caméra qui suit le bus
  if (S.view === "suivi" && S.follow && !S.followFree && !ptrs.size && !animating) {
    const v = vehicleOf(S.follow.pi, S.follow.k, S.follow.dk);
    if (v) { const [cx, cy] = centerFor(v.x, v.y, view.s); view.cx = cx; view.cy = cy; }
  }
  const C = { bg: css("--map-bg"), ink: css("--ink"), surf: css("--surface"), muted: css("--muted"), ok: css("--ok"), th: css("--theo"), me: css("--me"), font: css("--font-display") };
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  if (TILES_OK) { ctx.clearRect(0, 0, W, H); drawTiles(C.bg); } else { ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H); }
  const caseC = css("--map-case");
  const hl = highlight();
  const z = view.s / 9000;
  const lw = Math.max(1.6, Math.min(6, 2.2 * Math.pow(z, 0.55)));
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  const focus = hl.routes && hl.routes.size > 0;
  const journey = hl.legs.length > 0;
  const order = net.R.map((r, i) => i).sort((a, b) => ((hl.routes?.has(a) ? 1 : 0) - (hl.routes?.has(b) ? 1 : 0)) || ((net.R[a].m === 1) - (net.R[b].m === 1)));
  // écartement entre lignes parallèles (px) : un peu plus que l'épaisseur d'un trait
  const sp = lw * 1.35 + 1.4;
  const [vx0, vy1] = fromS(-40, -40), [vx1, vy0] = fromS(W + 40, H + 40);
  const visible = (b) => !(b[2] < vx0 || b[0] > vx1 || b[3] < vy0 || b[1] > vy1);
  for (const pass of [0, 1]) {
    for (const ri of order) {
      const on = !focus || hl.routes.has(ri);
      const strong = on && focus && !journey;
      const w = (net.R[ri].m === 1 ? lw * 1.3 : lw) * (strong ? 1.5 : 1);
      ctx.globalAlpha = !focus ? 1 : journey ? 0.16 : on ? 1 : 0.14;
      if (pass === 0) { if (ctx.globalAlpha < 0.5) continue; ctx.strokeStyle = caseC; ctx.lineWidth = w + 3; }
      else { ctx.strokeStyle = net.R[ri].c; ctx.lineWidth = w; }
      if (LN.length) { for (const f of lnByRoute[ri]) { if (visible(f.box)) { offsetPath(f, sp); ctx.stroke(); } } }
      else for (const k of routeShapes[ri]) { path(keyToPts.get(k)); ctx.stroke(); }
    }
  }
  ctx.globalAlpha = 1;
  for (const L of hl.legs) {
    path(L.pts);
    if (L.walk) { ctx.setLineDash([1, 7]); ctx.strokeStyle = C.ink; ctx.lineWidth = 4; ctx.stroke(); ctx.setLineDash([]); }
    else if (L.faded) { ctx.globalAlpha = 0.35; ctx.strokeStyle = L.c; ctx.lineWidth = lw * 1.6; ctx.stroke(); ctx.globalAlpha = 1; }
    else { ctx.strokeStyle = C.surf; ctx.lineWidth = lw * 2.6 + 5; ctx.stroke(); ctx.strokeStyle = L.c; ctx.lineWidth = lw * 2.6; ctx.stroke(); }
  }
  const hs = new Set(hl.stops);
  const showAll = z > 1.7;
  net.P.forEach((p, i) => {
    const on = hs.has(i), hub = hubs.has(i) && z > 0.75 && (!focus || net.pRoutes[i].some((r) => hl.routes.has(r)));
    if (!on && !showAll && !hub) return;
    const [x, y] = geoS(p[2], p[1]);
    if (x < -20 || y < -20 || x > W + 20 || y > H + 20) return;
    const r = on ? 4 : hub ? 3.6 : 2.6;
    ctx.beginPath(); ctx.arc(x, y, r, 0, 7);
    ctx.fillStyle = C.surf; ctx.fill(); ctx.lineWidth = on || hub ? 2 : 1.3; ctx.strokeStyle = on || hub ? C.ink : C.muted; ctx.stroke();
  });
  // étiquettes
  ctx.textBaseline = "middle";
  const placed = [], done = new Set();
  const tl = topInset() + 54, br = H - sheetInsetBottom();
  const label = (i, strong) => {
    if (done.has(i)) return;
    const p = net.P[i]; const [x, y] = geoS(p[2], p[1]);
    if (x < 0 || y < 0 || x > W || y > br) return;
    ctx.font = `${strong ? 700 : 600} ${strong ? 13.5 : z > 3 ? 13 : 12}px ${C.font}`;
    const w = ctx.measureText(p[0]).width;
    for (const side of [1, -1]) {
      const bx = side > 0 ? x + 8 : x - 8 - w, box = [bx - 2, y - 8, bx + w + 2, y + 8];
      if (box[0] < 2 || box[2] > W - 2) continue;
      if (!strong && placed.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
      placed.push(box); done.add(i);
      ctx.lineWidth = 4; ctx.strokeStyle = C.bg; ctx.strokeText(p[0], bx, y);
      ctx.fillStyle = strong ? C.ink : C.muted; ctx.fillText(p[0], bx, y);
      return;
    }
  };
  // réserve la zone des boutons du plan
  placed.push([W - 64, 0, W, tl + 200]);
  hl.ends.forEach(([i]) => label(i, true));
  if (S.view === "itineraire" && S.journeys[S.selJ]) S.journeys[S.selJ].legs.forEach((g) => { if (g.type === "ride") { const p = net.pats[g.pat]; label(net.Q[p.stops[g.bi]][0], true); label(net.Q[p.stops[g.ai]][0], true); } });
  if (hover && hover.kind === "stop") label(hover.i, true);
  if (hs.size && z > 1.1) [...hs].forEach((i) => label(i, false));
  if (z > 1.0) [...hubs].forEach((i) => label(i, false));
  if (showAll && z > 2.4) net.P.forEach((p, i) => label(i, false));
  hl.ends.forEach(([i, kind]) => {
    const p = net.P[i]; const [x, y] = geoS(p[2], p[1]);
    ctx.beginPath();
    if (kind === "to") roundRect(x - 7.5, y - 7.5, 15, 15, 3); else ctx.arc(x, y, 8, 0, 7);
    ctx.fillStyle = kind === "to" ? C.ink : C.surf; ctx.fill(); ctx.lineWidth = 3.5; ctx.strokeStyle = C.ink; ctx.stroke();
  });
  // ma position
  if (ME.pos) {
    const [x, y] = geoS(ME.pos[1], ME.pos[0]);
    const rr = Math.min(200, ME.acc / (111320 / view.s));
    if (rr > 10) { ctx.beginPath(); ctx.arc(x, y, rr, 0, 7); ctx.fillStyle = C.me; ctx.globalAlpha = 0.12; ctx.fill(); ctx.globalAlpha = 1; }
    ctx.beginPath(); ctx.arc(x, y, 8, 0, 7); ctx.fillStyle = "#fff"; ctx.fill();
    ctx.beginPath(); ctx.arc(x, y, 5.5, 0, 7); ctx.fillStyle = C.me; ctx.fill();
  }
  // bus en circulation
  lastVeh = [];
  if (showBuses || S.view === "suivi") {
    const vs = S.view === "suivi" && S.follow && !showBuses ? [vehicleOf(S.follow.pi, S.follow.k, S.follow.dk)].filter(Boolean) : vehicles();
    const sel = hl.trips;
    for (const v of vs) {
      if (hl.routes && hl.routes.size && !hl.routes.has(v.r)) continue;
      const [sx, sy] = toS(v.x, v.y);
      if (sx < -20 || sy < -20 || sx > W + 20 || sy > H + 20) continue;
      lastVeh.push({ ...v, sx, sy });
    }
    lastVeh.sort((a, b) => (sel?.has(a.pi + ":" + a.k) ? 1 : 0) - (sel?.has(b.pi + ":" + b.k) ? 1 : 0));
    const big = z > 1.3 || (sel && sel.size);
    for (const v of lastVeh) {
      const R = net.R[v.r], mine = sel?.has(v.pi + ":" + v.k), isHover = hover && hover.kind === "veh" && hover.v.pi === v.pi && hover.v.k === v.k;
      const dim = sel && sel.size && !mine;
      ctx.globalAlpha = dim ? 0.45 : 1;
      const rad = mine ? 13 : isHover ? 11 : big ? 9 : 6;
      if (mine) { ctx.beginPath(); ctx.arc(v.sx, v.sy, rad + 9, 0, 7); ctx.fillStyle = R.c; ctx.globalAlpha = 0.18; ctx.fill(); ctx.globalAlpha = 1; }
      ctx.save(); ctx.translate(v.sx, v.sy); ctx.rotate(-v.ang);
      ctx.beginPath(); ctx.moveTo(rad + 7, 0); ctx.lineTo(rad - 1, -5.5); ctx.lineTo(rad - 1, 5.5); ctx.closePath();
      ctx.fillStyle = C.ink; ctx.fill(); ctx.restore();
      ctx.beginPath(); ctx.arc(v.sx, v.sy, rad, 0, 7);
      ctx.fillStyle = R.c; ctx.fill(); ctx.lineWidth = 2.5; ctx.strokeStyle = C.surf; ctx.stroke();
      if (mine) { ctx.beginPath(); ctx.arc(v.sx, v.sy, rad + 3.5, 0, 7); ctx.lineWidth = 2.5; ctx.strokeStyle = C.ink; ctx.stroke(); }
      if (rad >= 9) {
        const txt = R.s;
        ctx.font = `700 ${txt.length > 2 ? (mine ? 10.5 : 9) : (mine ? 12.5 : 10.5)}px ${C.font}`; ctx.textAlign = "center"; ctx.fillStyle = R.t; ctx.fillText(txt, v.sx, v.sy + 0.5); ctx.textAlign = "start";
      }
      ctx.beginPath(); ctx.arc(v.sx + rad * 0.72, v.sy - rad * 0.72, rad >= 9 ? 3.8 : 2.6, 0, 7);
      ctx.fillStyle = v.live ? C.ok : C.th; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = C.surf; ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }
  // échelle (en haut à gauche sur mobile, en bas à droite sinon)
  const mpp = 111320 / view.s;
  const nice = [50, 100, 200, 250, 500, 1000, 2000, 5000, 10000, 20000].find((m) => m / mpp >= 56) || 20000;
  const len = nice / mpp;
  const mob = isMobile();
  const bx = mob ? 14 : W - len - 16, by = mob ? topInset() + 26 : H - 20;
  ctx.strokeStyle = C.ink; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(bx, by - 5); ctx.lineTo(bx, by); ctx.lineTo(bx + len, by); ctx.lineTo(bx + len, by - 5); ctx.stroke();
  ctx.font = `600 11.5px ${C.font}`; ctx.fillStyle = C.ink; ctx.textAlign = "center";
  ctx.lineWidth = 3; ctx.strokeStyle = C.bg; const st = nice >= 1000 ? nice / 1000 + " km" : nice + " m";
  ctx.strokeText(st, bx + len / 2, by - 10); ctx.fillText(st, bx + len / 2, by - 10); ctx.textAlign = "start";
  if (TILES_OK) {
    ctx.font = `500 10px ${C.font}`; ctx.textAlign = mob ? "left" : "right"; ctx.lineWidth = 3; ctx.strokeStyle = C.bg; ctx.fillStyle = C.muted;
    const at = "© les contributeurs d'OpenStreetMap", ax = mob ? 14 : W - 12, ay = mob ? topInset() + 44 : H - 6;
    ctx.strokeText(at, ax, ay); ctx.fillText(at, ax, ay); ctx.textAlign = "start";
  }
  placePop();
}

// ---------- caméra ----------
let anim = 0, animating = false;
// centre la vue pour que (x, y) tombe au milieu de la partie visible (au-dessus du panneau sur mobile)
function centerFor(x, y, s) { const b = sheetInsetBottom(), t = topInset(); return [x, y - (b - t) / 2 / s]; }
function animateTo(cx, cy, s) {
  s = Math.max(ZMIN, Math.min(ZMAX, s));
  cancelAnimationFrame(anim);
  if (reduceMotion || !W) { view.cx = cx; view.cy = cy; view.s = s; drawMap(); return; }
  const a = { cx: view.cx, cy: view.cy, s: view.s }, t0 = performance.now(), T = 450;
  animating = true;
  const step = (now) => {
    const u = Math.min(1, (now - t0) / T), e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
    view.s = Math.exp(Math.log(a.s) + (Math.log(s) - Math.log(a.s)) * e); view.cx = a.cx + (cx - a.cx) * e; view.cy = a.cy + (cy - a.cy) * e;
    paint(); if (u < 1) anim = requestAnimationFrame(step); else animating = false;
  };
  anim = requestAnimationFrame(step);
}
function centerOn(x, y, s, smooth) { const [cx, cy] = centerFor(x, y, s); if (smooth) animateTo(cx, cy, s); else { view.cx = cx; view.cy = cy; view.s = s; drawMap(); } }
function fitBox(pts, pad = 50) {
  if (!pts.length || !W) return;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  pts.forEach(([lo, la]) => { const x = PX(lo), y = PY(la); x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); });
  const visH = H - sheetInsetBottom() - topInset();
  const p = Math.min(pad, W / 5, visH / 5);
  const s = Math.max(ZMIN, Math.min((W - p * 2 - (isMobile() ? 40 : 0)) / Math.max(x1 - x0, 0.004), (visH - p * 2) / Math.max(y1 - y0, 0.003), 60000));
  centerOn((x0 + x1) / 2, (y0 + y1) / 2, s, true);
}
function fitJourney(j) { if (!j) return; const pts = []; j.legs.forEach((g) => { if (g.type === "ride") { const p = net.pats[g.pat]; for (let s = g.bi; s <= g.ai; s++) { const q = net.Q[p.stops[s]]; pts.push([q[2], q[1]]); } } else { [g.from, g.to].forEach((q) => pts.push([net.Q[q][2], net.Q[q][1]])); } }); fitBox(pts, 60); }
function fitLine(ri) { const pts = []; routeShapes[ri].forEach((k) => keyToPts.get(k).forEach((p) => pts.push(p))); fitBox(pts, 30); }
function fitStop(i) { const p = net.P[i]; centerOn(PX(p[2]), PY(p[1]), Math.max(view.s, 26000), true); }
function fitHome() { const pts = net.pats.filter((p) => !/^E/.test(net.R[p.r].s)).flatMap((p) => p.stops.map((q) => [net.Q[q][2], net.Q[q][1]])); fitBox(pts, 16); }
function fitMe() { if (!ME.pos) return; centerOn(PX(ME.pos[1]), PY(ME.pos[0]), Math.max(view.s, 30000), true); }

// ---------- interactions ----------
function hitTest(sx, sy) {
  let best = null, bd = 18 * 18;
  for (const v of lastVeh) { const d = (v.sx - sx) ** 2 + (v.sy - sy) ** 2; if (d < bd) { bd = d; best = { kind: "veh", v }; } }
  if (best) return best;
  bd = 15 * 15;
  net.P.forEach((p, i) => { const [x, y] = geoS(p[2], p[1]); const d = (x - sx) ** 2 + (y - sy) ** 2; if (d < bd) { bd = d; best = { kind: "stop", i }; } });
  return best;
}
const ptrs = new Map(); let moved = false, pinch0 = null, downAt = null;
const pos = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
cv.addEventListener("pointerdown", (e) => {
  cv.setPointerCapture(e.pointerId); cancelAnimationFrame(anim); animating = false;
  ptrs.set(e.pointerId, pos(e)); moved = false; downAt = pos(e);
  if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch0 = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, s: view.s, m: fromS((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) }; }
});
function userMoved() { if (S.view === "suivi" && !S.followFree) { S.followFree = true; renderFollow(); } }
cv.addEventListener("pointermove", (e) => {
  const [px, py] = pos(e);
  if (!ptrs.has(e.pointerId)) {
    if (e.pointerType === "mouse") { const h = hitTest(px, py); const key = h ? h.kind + (h.i ?? h.v.pi + ":" + h.v.k) : ""; const old = hover ? hover.kind + (hover.i ?? hover.v.pi + ":" + hover.v.k) : ""; cv.style.cursor = h ? "pointer" : ""; if (key !== old) { hover = h; drawMap(); } }
    return;
  }
  const [ox, oy] = ptrs.get(e.pointerId); ptrs.set(e.pointerId, [px, py]);
  if (ptrs.size === 1) {
    if (!moved && Math.hypot(px - downAt[0], py - downAt[1]) < 6) return;
    if (!moved) { moved = true; cv.classList.add("drag"); userMoved(); }
    view.cx -= (px - ox) / view.s; view.cy += (py - oy) / view.s; drawMap();
  } else if (ptrs.size === 2 && pinch0) {
    if (!moved) userMoved();
    moved = true;
    const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    view.s = Math.max(ZMIN, Math.min(ZMAX, pinch0.s * d / pinch0.d));
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    view.cx = pinch0.m[0] - (mx - W / 2) / view.s; view.cy = pinch0.m[1] + (my - H / 2) / view.s; drawMap();
  }
});
const up = (e) => { ptrs.delete(e.pointerId); if (ptrs.size < 2) pinch0 = null; if (ptrs.size === 1) { const [k] = ptrs.keys(); downAt = ptrs.get(k); } if (!ptrs.size) cv.classList.remove("drag"); };
cv.addEventListener("pointerup", (e) => { const wasMoved = moved; const single = ptrs.size === 1; up(e); if (!wasMoved && single) { const [px, py] = pos(e); clickMap(px, py); } });
cv.addEventListener("pointercancel", up);
cv.addEventListener("pointerleave", () => { if (hover) { hover = null; drawMap(); } });
cv.addEventListener("dblclick", (e) => { e.preventDefault(); const [px, py] = pos(e); zoomAt(px, py, 2, true); });
cv.addEventListener("wheel", (e) => {
  e.preventDefault(); cancelAnimationFrame(anim); animating = false;
  const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
  const [px, py] = pos(e); zoomAt(px, py, Math.exp(-Math.max(-300, Math.min(300, dy)) * (e.ctrlKey ? 0.01 : 0.0022)));
}, { passive: false });
function zoomAt(sx, sy, f, smooth) {
  // pendant le suivi, le zoom reste centré sur le bus
  if (S.view === "suivi" && !S.followFree) { view.s = Math.max(ZMIN, Math.min(ZMAX, view.s * f)); drawMap(); return; }
  const [x, y] = fromS(sx, sy); const s = Math.max(ZMIN, Math.min(ZMAX, view.s * f));
  const cx = x - (sx - W / 2) / s, cy = y + (sy - H / 2) / s;
  if (smooth) animateTo(cx, cy, s); else { view.s = s; view.cx = cx; view.cy = cy; drawMap(); }
}
const visCenter = () => [W / 2, (H - sheetInsetBottom() + topInset()) / 2];
$("#z-in").addEventListener("click", () => { const [x, y] = visCenter(); zoomAt(x, y, 1.8, true); });
$("#z-out").addEventListener("click", () => { const [x, y] = visCenter(); zoomAt(x, y, 1 / 1.8, true); });
$("#z-fit").addEventListener("click", () => {
  hidePop();
  if (S.view === "itineraire" && S.journeys[S.selJ]) fitJourney(S.journeys[S.selJ]);
  else if (S.view === "lignes" && S.line != null) fitLine(S.line);
  else if (S.view === "passages" && S.paStop != null) fitStop(S.paStop);
  else if (S.view === "suivi") { S.followFree = false; renderFollow(); followCam(true); }
  else fitHome();
});
$("#z-me").addEventListener("click", () => { if (ME.pos) fitMe(); else { toast("Recherche de votre position…", 2000); locate(() => { fitMe(); if (S.view === "accueil") renderHome(); }); } });
const busBtn = $("#z-bus");
const syncBusBtn = () => { busBtn.setAttribute("aria-pressed", showBuses); busBtn.title = showBuses ? "Masquer les bus en circulation" : "Afficher les bus en circulation"; };
busBtn.addEventListener("click", () => { showBuses = !showBuses; store.set("buses", showBuses); syncBusBtn(); toast(showBuses ? "Bus en circulation affichés" : "Bus masqués", 1500); drawMap(); });
syncBusBtn();
cv.tabIndex = 0;
cv.addEventListener("keydown", (e) => {
  const k = e.key, step = 80;
  if (k === "+" || k === "=") zoomAt(W / 2, H / 2, 1.5, true);
  else if (k === "-") zoomAt(W / 2, H / 2, 1 / 1.5, true);
  else if (k.startsWith("Arrow")) { userMoved(); view.cx += (k === "ArrowLeft" ? -step : k === "ArrowRight" ? step : 0) / view.s; view.cy += (k === "ArrowUp" ? step : k === "ArrowDown" ? -step : 0) / view.s; drawMap(); }
  else if (k === "Escape") hidePop();
  else return;
  e.preventDefault();
});

// ---------- info-bulle ancrée sur le plan ----------
const pop = $("#pop"); let popAt = null;
function hidePop() { pop.classList.remove("on"); popAt = null; }
function placePop() {
  if (!popAt) return;
  let sx, sy;
  if (popAt.veh) { const v = lastVeh.find((x) => x.pi === popAt.veh.pi && x.k === popAt.veh.k); if (!v) { hidePop(); return; } sx = v.sx; sy = v.sy; fillVehPop(v); }
  else [sx, sy] = toS(popAt.x, popAt.y);
  const pw = pop.offsetWidth || 240, ph = pop.offsetHeight || 140, maxY = H - sheetInsetBottom();
  let left = sx + 14, top = sy + 14;
  if (left + pw > W - 8) left = sx - pw - 14;
  if (top + ph > maxY - 8) top = sy - ph - 14;
  pop.style.left = Math.max(8, left) + "px"; pop.style.top = Math.max(topInset() + 8, top) + "px";
  pop.style.visibility = sx < -10 || sy < -10 || sx > W + 10 || sy > maxY + 10 ? "hidden" : "visible";
}
function fillVehPop(v) {
  const p = net.pats[v.pi];
  const nm = qName(p.stops[v.nextI]);
  const wait = v.next - nowMinF();
  const kind = net.R[p.r].m === 1 ? "tram" : "bus";
  const html = `<button type="button" class="x" aria-label="Fermer">×</button>
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;padding-right:22px">${badge(p.r)}<h3 style="margin:0;padding:0">→ ${esc(p.h)}</h3></div>
    <div class="sub">${v.atStop ? "À l'arrêt" : "Prochain arrêt"} : <b>${esc(nm)}</b>${v.atStop ? "" : ` · ${wait < 0.5 ? "imminent" : "dans " + Math.round(wait) + " min"}`}</div>
    <div class="sub" style="margin-top:6px;display:flex;gap:6px;align-items:center">${v.live ? `<i class="dotlive"></i>Temps réel${Math.abs(v.delay) >= 1 ? ` · ${v.delay > 0 ? "retard " + v.delay : "avance " + -v.delay} min` : " · à l'heure"}` : `<i class="dottheo"></i>Position d'après l'horaire théorique`}</div>
    <div class="acts"><button type="button" class="btn small primary" data-a="follow">Suivre ce ${kind}</button></div>`;
  if (pop.dataset.html !== html) { pop.innerHTML = html; pop.dataset.html = html; }
}
pop.addEventListener("click", (e) => {
  if (e.target.closest(".x")) return hidePop();
  const a = e.target.closest("[data-a]")?.dataset.a; if (!a) return;
  if (a === "follow" && popAt?.veh) { const { pi, k, dk } = popAt.veh; hidePop(); startFollow(pi, k, dk); return; }
  if (popAt?.stop == null) return;
  const best = popAt.stop; hidePop();
  if (a === "pa") { openPassages(best); fitStop(best); return; }
  if (a === "fav") { toggleFavStop(best); if (S.view === "accueil") renderHome(); return; }
  if (a === "from") { S.from = best; fromP.set(best); } else { S.to = best; toP.set(best); }
  itFollowNow = true; go("itineraire");
});
function clickMap(sx, sy) {
  const h = hitTest(sx, sy);
  if (!h) { hidePop(); return; }
  if (h.kind === "veh") { pop.dataset.html = ""; popAt = { veh: { pi: h.v.pi, k: h.v.k, dk: h.v.dk } }; fillVehPop(h.v); pop.classList.add("on"); placePop(); return; }
  const best = h.i, p = net.P[best];
  pop.dataset.html = "";
  pop.innerHTML = `<button type="button" class="x" aria-label="Fermer">×</button><h3>${esc(pName(best))}</h3><div class="badges">${net.pRoutes[best].map((r) => badge(r, "sm")).join("")}</div>
    <div class="acts"><button type="button" class="btn small primary" data-a="pa">Passages</button><button type="button" class="btn small" data-a="from">Partir d'ici</button><button type="button" class="btn small" data-a="to">Y aller</button><button type="button" class="btn small star" data-a="fav" aria-pressed="${isFavStop(best)}" aria-label="Favori" style="width:36px;padding:0">${starSvg}</button></div>`;
  popAt = { x: PX(p[2]), y: PY(p[1]), stop: best };
  pop.classList.add("on"); placePop();
}
// rafraîchit la position des bus toutes les 2 s (1 s pendant un suivi), seulement si la page est visible
setInterval(() => { if (!document.hidden && !ptrs.size && (showBuses || S.view === "suivi")) drawMap(); }, 1000);
