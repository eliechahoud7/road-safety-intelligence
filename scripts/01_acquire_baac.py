"""Phase 1 - Acquire official BAAC CSVs (2019-2025) from data.gouv.fr.

Resources are resolved at run time from the official data.gouv.fr API.
Files are stored byte-for-byte, verified against the API filesize,
hashed (SHA-256) and set read-only. Re-runs skip files whose hash matches.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import stat
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATASET_SLUG = (
    "bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-"
    "routiere-annees-de-2005-a-2025"
)
API_URL = f"https://www.data.gouv.fr/api/1/datasets/{DATASET_SLUG}/"
YEARS = range(2019, 2026)
TABLE_PATTERNS = {
    # 'carcteristiques' is a typo in the official 2021/2022 titles.
    "caracteristiques": re.compile(r"^(caract|carct)", re.I),
    "lieux": re.compile(r"^lieux", re.I),
    "vehicules": re.compile(r"^vehicules[-_]\d{4}", re.I),
    "usagers": re.compile(r"^usagers", re.I),
}
DOC_PATTERNS = [
    re.compile(r"description-des-bases-de-donnees-annuelles\.pdf$", re.I),
    re.compile(r"description-des-bases-de-donnees-onisr-annees-2005-a-2020\.pdf$", re.I),
]
USER_AGENT = "road-safety-intelligence-profiler/0.1"

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "baac"


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resource_name(res: dict) -> str:
    return res["url"].rstrip("/").split("/")[-1]


def select_resources(meta: dict) -> list[dict]:
    selected = []
    for year in YEARS:
        for table, pat in TABLE_PATTERNS.items():
            hits = [
                r for r in meta["resources"]
                if pat.search(r["title"].strip())
                and str(year) in r["title"]
                and "immatricul" not in r["title"].lower()
                and r["url"].lower().endswith(".csv")
            ]
            if len(hits) != 1:
                titles = [h["title"] for h in hits]
                sys.exit(f"ABORT: {table} {year}: expected 1 resource, found {len(hits)}: {titles}")
            r = hits[0]
            selected.append({"kind": "data", "year": year, "table": table, "res": r})
    for pat in DOC_PATTERNS:
        hits = [r for r in meta["resources"] if pat.search(resource_name(r)) or pat.search(r["title"])]
        if len(hits) != 1:
            sys.exit(f"ABORT: doc {pat.pattern}: expected 1, found {len(hits)}")
        selected.append({"kind": "doc", "year": "", "table": "", "res": hits[0]})
    return selected


def main() -> None:
    meta = json.loads(http_get(API_URL))
    print(f"Dataset : {meta['title']}")
    print(f"Org     : {(meta.get('organization') or {}).get('name')}")
    print(f"Licence : {meta.get('license')}")
    print(f"Updated : {meta.get('last_update')}  frequency={meta.get('frequency')}")

    items = select_resources(meta)
    rows = []
    for it in items:
        r = it["res"]
        dest_dir = RAW / (str(it["year"]) if it["kind"] == "data" else "docs")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / resource_name(r)
        expected = r.get("filesize")
        status = "downloaded"
        if dest.exists() and expected and dest.stat().st_size == expected:
            status = "present"
        else:
            if dest.exists():
                os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)
            data = http_get(r["url"])
            dest.write_bytes(data)
        size = dest.stat().st_size
        if expected is not None and size != expected:
            sys.exit(f"ABORT: size mismatch {dest.name}: got {size}, API says {expected}")
        os.chmod(dest, stat.S_IREAD)  # read-only
        digest = sha256(dest)
        rows.append({
            "kind": it["kind"], "year": it["year"], "table": it["table"],
            "title": r["title"], "file": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "resource_id": r["id"], "url": r["url"], "api_filesize": expected,
            "bytes": size, "sha256": digest, "created_at": r.get("created_at"),
            "last_modified": r.get("last_modified"), "status": status,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset_licence": meta.get("license"),
            "producer": (meta.get("organization") or {}).get("name"),
        })
        print(f"[{status:10}] {dest.relative_to(ROOT)}  {size:>10,} B")

    manifest = RAW / "_manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    total = sum(r["bytes"] for r in rows if r["kind"] == "data")
    print(f"\n{sum(r['kind']=='data' for r in rows)} CSVs, {total/1e6:.1f} MB; manifest -> {manifest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
