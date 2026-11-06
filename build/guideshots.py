# Refait les captures du mode d emploi (#22) : servir le dépôt en local (python3 -m http.server 8765), reconstruire test/index.html, copier info-trafic.json dans test/, puis lancer ce script.
import asyncio, sys
from playwright.async_api import async_playwright
from PIL import Image
U="http://localhost:8765/test/index.html"
OUT="/home/claude/mfggwwggff-horairesbus/guide/"
INIT = """sessionStorage.setItem('grm:splash','1'); localStorage.setItem('grm:nightSeen', JSON.stringify('2099-01-01')); localStorage.setItem('grm:updSeen','"2026-11-07"');
  localStorage.setItem('grm:favStops', JSON.stringify(['Strasbourg','Opéra-Cathédrale'])); localStorage.setItem('grm:stopNames', JSON.stringify({'Strasbourg':'Maison'}));
  localStorage.setItem('grm:favTrips', JSON.stringify([['Strasbourg','Maurencienne']])); localStorage.setItem('grm:stopNames', JSON.stringify({'Strasbourg':'Maison','Strasbourg|Maurencienne':'Boulot'}));
  localStorage.setItem('grm:myLines', JSON.stringify([])); localStorage.setItem('grm:buses','false'); localStorage.setItem('grm:pa', JSON.stringify('Opéra-Cathédrale')); localStorage.setItem('grm:alTr','[]');"""
RING = """(sel) => { document.querySelectorAll('.gring').forEach(x => x.remove()); const e = document.querySelector(sel); if (!e) return false; e.scrollIntoView({block:'nearest'}); const r = e.getBoundingClientRect(); const d = document.createElement('div');
  d.className = 'gring'; Object.assign(d.style, {position:'fixed', left:(r.left-6)+'px', top:(r.top-6)+'px', width:(r.width+12)+'px', height:(r.height+12)+'px', border:'3px solid #E8511C', borderRadius:'14px', zIndex:9999, pointerEvents:'none', boxShadow:'0 0 0 4px rgba(232,81,28,.18)'}); document.body.appendChild(d); return true; }"""
async def shot(pg, name, top=0, h=640):
    await pg.evaluate("document.querySelectorAll('.simu').forEach(e=>e.style.display='none')")
    await pg.wait_for_timeout(300)
    await pg.screenshot(path="/tmp/g.png")
    im = Image.open("/tmp/g.png").convert("RGB"); W = im.size[0]
    im = im.crop((0, int(top*2), W, int((top+h)*2))).resize((640, int(h*640/390)))
    im.save(OUT+name, "JPEG", quality=70, optimize=True, progressive=True)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":390,"height":844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        pg = await ctx.new_page(); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U); await pg.evaluate(INIT)
        n = [0]
        async def fresh(h):
            n[0] += 1
            await pg.goto(U+"?simu=2026-11-06T17:30&r=%d" % n[0] + h); await pg.wait_for_timeout(1800)
        # Passages
        await fresh("#passages"); await pg.evaluate("window.__t.setSheet('full')"); await pg.wait_for_timeout(500)
        print("ring passages", await pg.evaluate(RING, "#pa-res .chip")); await shot(pg, "passages.jpg", 0, 640)
        # Itinéraire : trajet favori depuis l'accueil
        await fresh("#accueil"); await pg.evaluate("window.__t.setSheet('full')"); await pg.wait_for_timeout(300)
        await pg.click("[data-trip='0']"); await pg.wait_for_timeout(1500)
        await pg.evaluate("window.__t.setSheet('full')"); await pg.wait_for_timeout(500)
        print("ring iti", await pg.evaluate(RING, ".itmore")); await shot(pg, "itineraire.jpg", 0, 640)
        # Mon bus
        await fresh("#accueil"); await pg.evaluate("window.__t.startFollow(42, 123, window.__t.todayIdx(), null, null)"); await pg.wait_for_timeout(1200)
        await pg.evaluate("window.__t.setSheet('full')"); await pg.wait_for_timeout(900)
        print("ring monbus", await pg.evaluate(RING, "#mb-b9 .b9")); await shot(pg, "monbus.jpg", 0, 640)
        # Info trafic
        await fresh("#trafic"); await pg.evaluate("window.__t.setSheet('full')"); await pg.wait_for_timeout(800)
        print("ring trafic", await pg.evaluate(RING, "#tr-res .tritem")); await shot(pg, "trafic.jpg", 0, 640)
        # Profil
        await fresh("#accueil"); await pg.click("#prof-btn"); await pg.wait_for_timeout(500)
        print("ring profil", await pg.evaluate(RING, "#prof [data-plist='stops'] .prow .pact")); await shot(pg, "profil.jpg", 0, 640)
        # Guide page (for maquette)
        await pg.evaluate("document.querySelectorAll('.gring').forEach(e=>e.remove())")
        await pg.click("[data-pg='guide']"); await pg.wait_for_timeout(400)
        await pg.evaluate("document.querySelectorAll('.simu').forEach(e=>e.style.display='none')")
        await pg.screenshot(path="/home/claude/scripts/m22_guide.png")
        await pg.click("details.gch[data-g='monbus'] summary"); await pg.wait_for_timeout(700)
        await pg.evaluate("document.querySelector('details.gch[data-g=monbus]').scrollIntoView({block:'start'})"); await pg.wait_for_timeout(300)
        await pg.screenshot(path="/home/claude/scripts/m22_chap.png")
        await pg.click("[data-inst]"); await pg.wait_for_timeout(500)
        await pg.screenshot(path="/home/claude/scripts/m22_inst1.png")
        await pg.click("#updpop .up-go"); await pg.wait_for_timeout(700); await pg.screenshot(path="/home/claude/scripts/m22_inst2.png")
        await pg.click("#updpop .up-skip"); await pg.wait_for_timeout(300)
        await pg.click("#prof-back"); await pg.wait_for_timeout(300)
        await pg.screenshot(path="/home/claude/scripts/m22_prof.png")
        await pg.click("[data-pg='news']"); await pg.wait_for_timeout(300)
        await pg.evaluate("document.querySelectorAll('.simu').forEach(e=>e.style.display='none')")
        await pg.screenshot(path="/home/claude/scripts/m23_news.png")
        await pg.click("[data-upd='0']"); await pg.wait_for_timeout(500)
        await pg.screenshot(path="/home/claude/scripts/m23_slide1.png")
        await pg.evaluate("document.querySelector('#updpop .up-track').scrollTo({left: 99999})"); await pg.wait_for_timeout(600)
        await pg.screenshot(path="/home/claude/scripts/m23_slide4.png")
        # Bienvenue (1re ouverture)
        ctx2 = await b.new_context(viewport={"width":390,"height":844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        p2 = await ctx2.new_page(); p2.on("pageerror", lambda e: errs.append(str(e)))
        await p2.goto(U+"?simu=2026-11-06T17:30"); await p2.evaluate("sessionStorage.setItem('grm:splash','1'); localStorage.setItem('grm:nightSeen', JSON.stringify('2099-01-01'))")
        await p2.goto(U+"?simu=2026-11-06T17:30"); await p2.wait_for_timeout(2500)
        await p2.evaluate("document.querySelectorAll('.simu').forEach(e=>e.style.display='none')")
        await p2.screenshot(path="/home/claude/scripts/m22_welcome.png")
        # Mon bus #25 : remonter la liste
        await fresh("#accueil"); await pg.evaluate("window.__t.startFollow(42, 123, window.__t.todayIdx(), null, null)"); await pg.wait_for_timeout(1200)
        await pg.evaluate("window.__t.setSheet('full')"); await pg.wait_for_timeout(900)
        await pg.evaluate("document.querySelectorAll('.simu').forEach(e=>e.style.display='none')")
        await pg.screenshot(path="/home/claude/scripts/m25_bus.png")
        print("arrêts affichés:", await pg.evaluate("document.querySelectorAll('#mb-track .mbr').length"), "premier:", await pg.evaluate("document.querySelector('#mb-track .mbr')?.textContent.trim().slice(0,30)"))
        await pg.evaluate("document.querySelector('#scroll').scrollTo({top:0})"); await pg.wait_for_timeout(400)
        await pg.screenshot(path="/home/claude/scripts/m25_top.png")
        print(errs); await b.close()
asyncio.run(main())
