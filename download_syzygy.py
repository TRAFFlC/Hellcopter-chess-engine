import urllib.request
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

SYZYGY_DIR = r"e:\world\python\chess\dist\syzygy"
SSESSE_URL = "http://tablebase.sesse.net/syzygy/3-4-5/"
MAX_WORKERS = 8

os.makedirs(SYZYGY_DIR, exist_ok=True)

CRITICAL_3_4 = [
    "KQvK.rtbw", "KQvK.rtbz",
    "KRvK.rtbw", "KRvK.rtbz",
    "KBvK.rtbw", "KBvK.rtbz",
    "KNvK.rtbw", "KNvK.rtbz",
    "KPK.rtbw",  "KPK.rtbz",
    "KQvKQ.rtbw", "KQvKQ.rtbz",
    "KQvKR.rtbw", "KQvKR.rtbz",
    "KQvKB.rtbw", "KQvKB.rtbz",
    "KQvKN.rtbw", "KQvKN.rtbz",
    "KQvKP.rtbw", "KQvKP.rtbz",
    "KRvKR.rtbw", "KRvKR.rtbz",
    "KRvKB.rtbw", "KRvKB.rtbz",
    "KRvKN.rtbw", "KRvKN.rtbz",
    "KRvKP.rtbw", "KRvKP.rtbz",
    "KBvKB.rtbw", "KBvKB.rtbz",
    "KBvKN.rtbw", "KBvKN.rtbz",
    "KBvKP.rtbw", "KBvKP.rtbz",
    "KNvKN.rtbw", "KNvKN.rtbz",
    "KNvKP.rtbw", "KNvKP.rtbz",
    "KPKP.rtbw",  "KPKP.rtbz",
    "KQQvK.rtbw", "KQQvK.rtbz",
    "KQRvK.rtbw", "KQRvK.rtbz",
    "KQBvK.rtbw", "KQBvK.rtbz",
    "KQNvK.rtbw", "KQNvK.rtbz",
    "KRRvK.rtbw", "KRRvK.rtbz",
    "KRBvK.rtbw", "KRBvK.rtbz",
    "KRNvK.rtbw", "KRNvK.rtbz",
    "KRPvK.rtbw", "KRPvK.rtbz",
    "KBBvK.rtbw", "KBBvK.rtbz",
    "KBNvK.rtbw", "KBNvK.rtbz",
    "KNNvK.rtbw", "KNNvK.rtbz",
    "KBPvK.rtbw", "KBPvK.rtbz",
    "KNPvK.rtbw", "KNPvK.rtbz",
    "KPPvK.rtbw", "KPPvK.rtbz",
]

def download_one(fname):
    dest = os.path.join(SYZYGY_DIR, fname)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return fname, "skip", 0
    
    url = f"{SSESSE_URL}{fname}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as response:
            with open(dest, 'wb') as f:
                f.write(response.read())
        size = os.path.getsize(dest)
        return fname, "ok", size
    except Exception as e:
        return fname, "fail", str(e)

def main():
    import sys
    critical_only = "--critical" in sys.argv
    
    if critical_only:
        files = [f for f in CRITICAL_3_4]
        print(f"Downloading CRITICAL 3-4 piece files only ({len(files)} files)")
    else:
        print("Fetching file list from Sesse server...")
        try:
            req = urllib.request.Request(SSESSE_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                html = response.read().decode('utf-8', errors='ignore')
            files = sorted(set(re.findall(r'href="([^"]+\.rtb[wxz])"', html)))
            print(f"Found {len(files)} Syzygy files")
        except Exception as e:
            print(f"Error: {e}")
            return
    
    print(f"Downloading with {MAX_WORKERS} threads...")
    print()
    
    success = 0
    skipped = 0
    failed = 0
    total_bytes = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_one, f): f for f in files}
        
        for i, future in enumerate(as_completed(futures)):
            fname, status, result = future.result()
            
            if status == "ok":
                success += 1
                total_bytes += result
                if success % 5 == 0:
                    print(f"  Progress: {success} downloaded ({total_bytes/1024/1024:.1f} MB)")
            elif status == "skip":
                skipped += 1
            else:
                failed += 1
                print(f"  FAILED: {fname}")
    
    print()
    print(f"Download complete:")
    print(f"  Downloaded: {success} files ({total_bytes/1024/1024:.1f} MB)")
    print(f"  Skipped: {skipped} files")
    print(f"  Failed: {failed} files")
    
    all_files = os.listdir(SYZYGY_DIR)
    total_size = sum(os.path.getsize(os.path.join(SYZYGY_DIR, f)) for f in all_files)
    print(f"  Total: {len(all_files)} files ({total_size/1024/1024:.1f} MB)")

if __name__ == "__main__":
    main()
