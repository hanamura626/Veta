import asyncio
import os
import time

from camoufox.async_api import AsyncCamoufox
from PIL import Image

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
    # (Kode deteksi kotak centang tetap sama)
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

# --- FUNGSI BARU: DETEKSI WARNA HIJAU ---
def check_green_success(path, rx0, ry0, rx1, ry1):
    """Mendeteksi apakah ada lingkaran hijau (centang sukses) di area widget."""
    im = Image.open(path).convert("RGB")
    W, H = im.size
    px = im.load()
    x0, x1 = max(0, int(rx0)), min(W, int(rx1))
    y0, y1 = max(0, int(ry0)), min(H, int(ry1))
    
    green_pixels = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y]
            # Deteksi warna hijau Cloudflare: G tinggi, R dan B rendah
            if g > 100 and r < 100 and b < 100:
                green_pixels += 1
                
    # Jika ada lebih dari 50 piksel hijau, anggap sukses (centang muncul)
    if green_pixels > 50:
        return True
    return False

async def _solve_once(max_wait=60):
    proxy_url = os.environ.get("PROXY_URL", "")
    proxy_opt = {"server": proxy_url} if proxy_url else None
    
    print("[ts] Memulai browser Camoufox...", flush=True)
    async with AsyncCamoufox(headless=False, humanize=True, proxy=proxy_opt) as browser:
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
        page = await ctx.new_page()
        
        try:
            print(f"[ts] Membuka {URL}", flush=True)
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[ts] Gagal membuka halaman: {type(e).__name__}", flush=True)
            return ""
        
        await asyncio.sleep(8)
        rect = await page.evaluate(RECT_JS)
        print(f"[ts] Posisi Widget: {rect}", flush=True)
        
        if not rect:
            print("[ts] Widget Turnstile tidak ditemukan.", flush=True)
            await page.screenshot(path=SHOT)
            return ""
            
        t0 = time.time()
        clicked = False
        
        while time.time() - t0 < max_wait:
            await asyncio.sleep(5)
            
            # 1. Cek via Token DOM (Paling Akurat)
            tok = await page.evaluate(TOKEN_JS)
            if tok:
                print(f"[ts] ✅ SUKSES (Token didapat) setelah {time.time()-t0:.0f} detik.", flush=True)
                return tok
            
            # 2. Cek via Visual (Warna Hijau)
            await page.screenshot(path=SHOT)
            if check_green_success(SHOT, rect["x"], rect["y"], rect["x"] + rect["w"], rect["y"] + rect["h"]):
                print(f"[ts] 🟢 SUKSES (Centang Hijau terdeteksi visual) setelah {time.time()-t0:.0f} detik.", flush=True)
                # Karena visual hijau, kita tetap coba ambil tokennya
                tok = await page.evaluate(TOKEN_JS)
                return tok if tok else "VISUAL_SUCCESS_TOKEN_NOT_FOUND"
            
            # 3. Jika belum sukses, cari kotak centang dan klik
            fb = find_checkbox(SHOT, rect["x"] - 8, rect["y"] + 2, rect["x"] + 45, rect["y"] + rect["h"] - 2)
            print(f"[ts] Waktu: {time.time()-t0:.0f}s | Deteksi Kotak: {fb}", flush=True)
            
            if fb and not clicked:
                cx, cy = fb
                print(f"[ts] 🖱️ Mengklik kotak di ({cx}, {cy})...", flush=True)
                await page.mouse.move(cx - 16, cy + 9)
                await asyncio.sleep(0.45)
                await page.mouse.move(cx - 6, cy + 4)
                await asyncio.sleep(0.35)
                await page.mouse.move(cx, cy)
                await asyncio.sleep(0.3)
                await page.mouse.down(); await asyncio.sleep(0.14); await page.mouse.up()
                clicked = True
                
        print(f"[ts] ❌ GAGAL. Waktu {max_wait} detik habis.", flush=True)
        await page.screenshot(path=SHOT)
        return ""

def solve(max_wait=60) -> str:
    tok = asyncio.run(_solve_once(max_wait))
    if tok and tok != "VISUAL_SUCCESS_TOKEN_NOT_FOUND":
        with open(os.path.join(OUT, "tokens.txt"), "a") as f:
            f.write(tok + "\n")
    return tok

if __name__ == "__main__":
    print("=== MEMULAI PROSES BYPASS (SINGLE ATTEMPT) ===", flush=True)
    token = solve(max_wait=60) 
    
    if token:
        print(f"=== ✅ SUKSES! TOKEN: {token[:30]}... ===", flush=True)
    else:
        print("=== ❌ GAGAL MENDAPATKAN TOKEN ===", flush=True)
