"""Acquire IGN ADMIN EXPRESS COG editions matching BAAC years 2019-2025.

Source: IGN Géoplateforme download service (Atom feed), referenced by the
data.gouv.fr dataset "ADMIN EXPRESS" (licence: Licence Ouverte 2.0, 'lov2').
One edition per BAAC year (COG of 1 January of that year). Archives are kept
byte-for-byte (read-only), verified against the IGN length + MD5, hashed with
SHA-256, and only the COMMUNE / DEPARTEMENT layers are extracted (bsdtar).
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "data" / "raw" / "geography"
ARCH = GEO / "admin_express_cog" / "archives"
EXTR = GEO / "admin_express_cog" / "extracted"
FEED = "https://data.geopf.fr/telechargement/resource/ADMIN-EXPRESS-COG/"
UA = "road-safety-intelligence-profiler/0.1"
def find_bsdtar() -> str:
    """Locate a libarchive-based tar able to read .7z archives, on any platform.

    Order: `bsdtar` on PATH (Linux: package libarchive-tools), the Windows 10/11 built-in tar.exe,
    then `tar` on PATH if it is bsdtar (macOS default). GNU tar cannot read 7z and is rejected.
    """
    candidates = [shutil.which("bsdtar"), r"C:\Windows\System32\tar.exe", shutil.which("tar")]
    for c in candidates:
        if not c or not os.path.exists(c):
            continue
        try:
            version = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if "bsdtar" in version or "libarchive" in version:
            return c
    sys.exit("ABORT: no libarchive-based tar (bsdtar) found to extract .7z archives. "
             "Windows 10/11: built-in tar.exe; macOS: built-in tar; Linux: install 'libarchive-tools'.")


BSDTAR = find_bsdtar()

EDITIONS = {  # BAAC year -> IGN resource id (one edition per COG year)
    2019: "ADMIN-EXPRESS-COG_2-0__SHP__FRA_2019-09-24",
    2020: "ADMIN-EXPRESS-COG_2-1__SHP__FRA_2020-11-20",
    2021: "ADMIN-EXPRESS-COG_3-0__SHP_LAMB93_FXX_2021-05-19",
    2022: "ADMIN-EXPRESS-COG_3-1__SHP_LAMB93_FXX_2022-04-15",
    2023: "ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2023-05-03",
    2024: "ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22",
    2025: "ADMIN-EXPRESS-COG_4-0__GPKG_LAMB93_FXX_2025-01-01",
}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=600) as r:
        return r.read()


def digest(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ARCH.mkdir(parents=True, exist_ok=True)
    EXTR.mkdir(parents=True, exist_ok=True)
    rows = []
    for year, rid in EDITIONS.items():
        feed = get(FEED + rid).decode("utf-8")
        edition_date = re.search(r"<gpf_dl:editionDate>(.*?)<", feed).group(1)
        for e in re.findall(r"<entry>(.*?)</entry>", feed, flags=re.S):
            url = re.search(r'href="([^"]+)"', e).group(1)
            if not url.endswith(".7z"):
                continue
            length = int(re.search(r'gpf_dl:length="(\d+)"', e).group(1))
            md5 = re.search(r"<content>(.*?)</content>", e).group(1).strip()
            dest = ARCH / url.rsplit("/", 1)[1]
            status = "present"
            if not (dest.exists() and dest.stat().st_size == length and digest(dest, "md5") == md5):
                if dest.exists():
                    os.chmod(dest, stat.S_IREAD | stat.S_IWRITE)
                print(f"downloading {dest.name} ({length/1e6:.1f} MB)...", flush=True)
                tmp = dest.with_suffix(".part")
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=600) as r, tmp.open("wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
                status = "downloaded"
            size, got_md5 = dest.stat().st_size, digest(dest, "md5")
            if size != length or got_md5 != md5:
                sys.exit(f"ABORT {dest.name}: size {size}/{length}, md5 {got_md5}/{md5}")
            os.chmod(dest, stat.S_IREAD)
            # selective extraction of commune + departement layers (all sidecar files)
            # short flat folder per BAAC year (archive paths exceed Windows MAX_PATH)
            out = EXTR / str(year)
            out.mkdir(exist_ok=True)
            pats = ["*.gpkg"] if "GPKG" in rid else ["*/COMMUNE.*", "*/DEPARTEMENT.*"]
            listing = subprocess.run([BSDTAR, "-tf", str(dest), *pats], check=True,
                                     capture_output=True, text=True).stdout.split()
            names = [p.rsplit("/", 1)[1] for p in listing if not p.endswith("/")]
            if len(names) != len(set(names)):
                sys.exit(f"ABORT {dest.name}: ambiguous layer files {listing}")
            depth = listing[0].count("/")
            subprocess.run([BSDTAR, "-xf", str(dest), "-C", str(out),
                            f"--strip-components={depth}", *pats], check=True)
            rows.append({
                "baac_year": year, "resource_id": rid, "edition_date": edition_date,
                "archive": str(dest.relative_to(ROOT)).replace("\\", "/"), "url": url,
                "bytes": size, "md5_ign": md5, "md5_verified": got_md5 == md5,
                "sha256": digest(dest, "sha256"), "status": status,
                "licence": "Licence Ouverte 2.0 (data.gouv.fr 'lov2')", "producer": "IGN",
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            print(f"[{status}] {dest.name}  md5 OK  -> extracted to {out.relative_to(ROOT)}", flush=True)
    with (GEO / "_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} archives, {sum(r['bytes'] for r in rows)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
