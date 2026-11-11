"""Acquire INSEE Code officiel géographique (COG) history files, millésime 2026.

Source: insee.fr (page 8740222 "Code officiel géographique au 1er janvier 2026"),
listed in the INSEE data.gouv.fr dataset 58c984b088ee386cdb1261f3 (licence 'fr-lo',
Licence Ouverte). Files are stored byte-for-byte, SHA-256 hashed, set read-only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import stat
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "raw" / "geography" / "insee_cog" / "2026"
UA = "road-safety-intelligence-profiler/0.1"
DATASET_API = "https://www.data.gouv.fr/api/1/datasets/58c984b088ee386cdb1261f3/"
FILES = {
    "v_mvt_commune_2026.csv": "Liste des évènements survenus aux communes, arrondissements municipaux, communes associées et communes déléguées depuis 1943",
    "v_commune_depuis_1943.csv": "Communes depuis 1943 (couples code-libellé avec période de validité)",
}
BASE = "https://www.insee.fr/fr/statistiques/fichier/8740222/"


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
        return r.read()


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    meta = json.loads(get(DATASET_API))
    res = {r["url"]: r for r in meta["resources"]}
    rows = []
    for name, desc in FILES.items():
        url = BASE + name
        dest = DEST / name
        status = "present"
        if not dest.exists():
            dest.write_bytes(get(url))
            status = "downloaded"
        os.chmod(dest, stat.S_IREAD)
        r = res.get(url, {})
        rows.append({
            "file": str(dest.relative_to(ROOT)).replace("\\", "/"), "url": url, "description": desc,
            "millesime": "COG au 1er janvier 2026", "data_gouv_resource_id": r.get("id"),
            "data_gouv_last_modified": r.get("last_modified"),
            "bytes": dest.stat().st_size, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "producer": meta["organization"]["name"], "licence": f"{meta['license']} (Licence Ouverte)",
            "status": status, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        print(f"[{status}] {dest.relative_to(ROOT)} {rows[-1]['bytes']:,} B")
    with (DEST.parent / "_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
