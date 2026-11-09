import asyncio
import os
import time

from camoufox.async_api import AsyncCamoufox
from PIL import Image

# URL dan Sitekey disesuaikan dengan halaman registrasi DNSHE
URL = "https://my.dnshe.com/register.php?language=english"
SITEKEY = "0x4AAAAAACEqUetzorNQQ_pi" 

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
SHOT = os.path.join(OUT, "ts_shot.png")

RECT_JS = """() => {
    const w = document.querySelector('input[name="cf-turnstile-response"]');
    if (!w) return null;
    let e = w.parentElement;
    while (e) {
        const r = e.getBoundingClientRect();
        if (r.width > 150 && r.height > 40) return {x: r.x, y: r.y, w: r.width, h: r.height};
        e = e.parentElement;
    }
    return null;
}"""

TOKEN_JS = """() => {
    const w = document.querySelector('input[name="cf-turnstile-response"]');
    return (w && w.value) ? w.value : '';
}"""

def _gray(v):
    return sum(v) / 3.0

def find_checkbox(path, rx0, ry0, rx1, ry1, thr=215):
    """cari kotak centang: persegi ber-border gelap, interior terang."""
    im = Image.open(path).convert("RGB")
    W, H = im.size
    px = im.load()
    x0, x1 = max(0, int(rx0)), min(W, int(rx1))
    y0, y1 = max(0, int(ry0)), min(H, int(ry1))
    cand = {}
    for y in range(y0, y1):
        xs = [x for x in range(x0, x1) if _gray(px[x, y]) < thr]
        runs = []
        if xs:
            s = p = xs[0]
            for x in xs[1:]:
                if x == p + 1:
                    p = x
                else:
                    runs.append((s, p)); s = p = x
            runs.append((s, p))
        for (a, b) in runs:
            if 10 <= b - a + 1 <= 34:
                cand.setdefault((a, b), []).append(y)
    for (a, b), ys in cand.items():
        ys = sorted(ys)
        top, bot = ys[0], ys[-1]
        if bot - top < 8 or bot - top > 34 or len(ys) < 2:
            continue
        mid = list(range(top + 2, bot - 1))
        if len(mid) < 4:
            continue
        if sum(1 for y in mid if _gray(px[a + 1, y]) < thr) < 0.5 * len(mid):
            continue
        if sum(1 for y in mid if _gray(px[b - 1, y]) < thr) < 0.5 * len(mid):
            continue
        inner = sum(1 for y in mid for x in range(a + 3, b - 2) if _gray(px[x, y]) < 225)
        if inner > 0.12 * len(mid) * max(1, (b - 2) - (a + 3)):
            continue
        return ((a + b) // 2, (top + bot) // 2)
    return None

async def _solve_once(attempts=2, max_wait=200):
    print("[ts] Memulai browser Camoufox...", flush=True)
    async with AsyncCamoufox(headless=False, humanize=True) as browser:
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
        page = await ctx.new_page()
        for att in range(1, attempts + 1):
            try:
                print(f"[ts] Attempt {att}: Membuka {URL}", flush=True)
                await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"[ts] goto err {type(e).__name__}", flush=True)
                continue
            
            await asyncio.sleep(8)
            rect = await page.evaluate(RECT_JS)
            print(f"[ts] attempt {att}: rect={rect}", flush=True)
            if not rect:
                continue
                
            t0 = time.time()
            clicked = False
            while time.time() - t0 < max_wait:
                await asyncio.sleep(8)
                tok = await page.evaluate(TOKEN_JS)
                if tok:
                    print(f"[ts] TOKEN OK ({len(tok)} ch) setelah {time.time()-t0:.0f}s", flush=True)
                    return tok
                
                await page.screenshot(path=SHOT)
                # area kiri widget (checkbox ada di sisi kiri panel)
                fb = find_checkbox(SHOT, rect["x"] - 8, rect["y"] + 2,
                                   rect["x"] + 45, rect["y"] + rect["h"] - 2)
                print(f"[ts] t={time.time()-t0:.0f}s cb={fb}", flush=True)
                
                if fb and not clicked:
                    cx, cy = fb
                    print(f"[ts] KLIK checkbox ({cx},{cy})", flush=True)
                    await page.mouse.move(cx - 16, cy + 9)
                    await asyncio.sleep(0.45)
                    await page.mouse.move(cx - 6, cy + 4)
                    await asyncio.sleep(0.35)
                    await page.mouse.move(cx, cy)
                    await asyncio.sleep(0.3)
                    await page.mouse.down(); await asyncio.sleep(0.14); await page.mouse.up()
                    clicked = True
                    await asyncio.sleep(5)
                elif fb and clicked:
                    # klik ulang (mis. challenge gagal)
                    cx, cy = fb
                    await page.mouse.click(cx, cy)
                    await asyncio.sleep(5)
                    
        # Simpan screenshot terakhir sebelum browser ditutup (jika gagal)
        await page.screenshot(path=SHOT)
    return ""

def solve(attempts=2, max_wait=200) -> str:
    tok = asyncio.run(_solve_once(attempts, max_wait))
    if tok:
        with open(os.path.join(OUT, "tokens.txt"), "a") as f:
            f.write(tok + "\n")
    return tok

if __name__ == "__main__":
    print("=== MEMULAI PROSES BYPASS TURNSTILE ===", flush=True)
    token = solve()
    if token:
        print(f"=== SUKSES! TOKEN DIDAPATKAN: {token[:30]}... ===", flush=True)
    else:
        print("=== GAGAL MENDAPATKAN TOKEN ===", flush=True)
