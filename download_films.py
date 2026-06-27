"""
Reads films_with_download.json, visits each film's VidTube page,
builds the 4 quality URLs (_x / _h / _n / _l), extracts the direct
CDN download link for each quality, and downloads the file into:

    downloads/
    └── <film name>/
        ├── 1080p/
        │   └── <filename>.mp4
        ├── 720p/
        ├── 480p/
        └── 240p/

Usage:
    python download_films.py

    # Download only specific qualities (edit QUALITIES below)
    # Skip films already downloaded (resume-safe)

Dependencies: pip install requests beautifulsoup4
"""

import json
import re
import time
import logging
import requests
from pathlib import Path
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────

INPUT_FILE   = "films_with_download.json"
DOWNLOAD_DIR = Path(".")

# Comment out any quality you don't want
QUALITIES = {
    "1080p": "_x",
    "720p":  "_h",
    "480p":  "_n",
}

DELAY        = 0      # seconds between page requests
CHUNK_SIZE   = 1024 * 1024   # 1 MB download chunks

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://vidtube.one/",
}

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_name(name: str) -> str:
    """Strip characters that are illegal in folder/file names."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def build_quality_url(vidtube_url: str, suffix: str) -> str:
    """
    Turn  https://vidtube.one/d/y6f42c7c0olg.html
    into  https://vidtube.one/d/y6f42c7c0olg_x      (no .html, add suffix)
    """
    base = vidtube_url.rstrip("/")
    if base.endswith(".html"):
        base = base[:-5]          # remove .html
    return base + suffix


def fetch_html(session: requests.Session, url: str) -> str | None:
    try:
        r = session.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.text
    except requests.RequestException as exc:
        log.warning("  Fetch failed (%s): %s", url, exc)
        return None


def extract_direct_link(html: str) -> str:
    """
    Extract the CDN mp4 URL from the direct-download page.

    Target element:
        <a href="https://serv-stream-cdn*.mp4?..." class="btn btn-gradient submit-btn">
    """
    soup = BeautifulSoup(html, "html.parser")
    btn  = soup.select_one("a.btn.btn-gradient.submit-btn[href]")
    if btn:
        return btn.get("href", "").strip()
    return ""


def download_file(session: requests.Session,
                  url: str,
                  dest: Path,
                  film_name: str,
                  quality: str) -> bool:
    """Stream-download url → dest, show progress, skip if already done."""
    if dest.exists() and dest.stat().st_size > 0:
        log.info("    [skip] Already exists: %s", dest.name)
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")

    try:
        with session.get(url, headers=HEADERS, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0

            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded / total * 100
                            print(f"\r    Downloading {quality}  {pct:5.1f}%  "
                                  f"({downloaded // 1_048_576} / {total // 1_048_576} MB)",
                                  end="", flush=True)

            print()   # newline after progress
            tmp.rename(dest)
            log.info("    ✓ Saved: %s", dest)
            return True

    except requests.RequestException as exc:
        log.error("    Download failed: %s", exc)
        if tmp.exists():
            tmp.unlink()
        return False


def get_filename_from_url(url: str, fallback: str) -> str:
    """Extract filename from CDN URL, or use fallback."""
    path = url.split("?")[0].rstrip("/")
    name = path.split("/")[-1]
    return name if name.endswith(".mp4") else fallback + ".mp4"

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not Path(INPUT_FILE).exists():
        log.error("Input file '%s' not found.", INPUT_FILE)
        return

    with open(INPUT_FILE, encoding="utf-8") as fh:
        films: list[dict] = json.load(fh)

    # Only process films that have a VidTube link
    eligible = [f for f in films if f.get("vidtube_download")]
    log.info("Loaded %d films — %d have a VidTube link.", len(films), len(eligible))

    with requests.Session() as session:
        for fi, film in enumerate(eligible, start=1):
            film_name    = film.get("name", f"film_{fi}")
            vidtube_url  = film["vidtube_download"]
            folder_name  = safe_name(film_name)

            log.info("━" * 60)
            log.info("[%d/%d] %s", fi, len(eligible), film_name)

            for quality, suffix in QUALITIES.items():
                quality_url = build_quality_url(vidtube_url, suffix)
                log.info("  [%s] Fetching: %s", quality, quality_url)

                html = fetch_html(session, quality_url)
                time.sleep(DELAY)
                if not html:
                    log.warning("  [%s] Could not load quality page — skipping.", quality)
                    continue

                direct_url = extract_direct_link(html)
                if not direct_url:
                    log.warning("  [%s] Direct download link not found — skipping.", quality)
                    continue

                log.info("  [%s] Direct link: %s", quality, direct_url[:80] + "…")

                filename = get_filename_from_url(direct_url, folder_name)
                dest     = DOWNLOAD_DIR / folder_name / quality / filename

                download_file(session, direct_url, dest, film_name, quality)
                time.sleep(DELAY)

    log.info("━" * 60)
    log.info("All done. Files saved in '%s/'.", DOWNLOAD_DIR)


if __name__ == "__main__":
    main()
