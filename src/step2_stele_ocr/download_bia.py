"""Download original images from Vietnamica image links (one URL per line)."""

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]


def image_links(lines):
    seen = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = urlsplit(line)
        if parsed.hostname == "gallery.vietnamica.online" and parsed.path == "/api/image.php":
            links = parse_qs(parsed.query).get("links", [])
            if not links:
                raise ValueError("Gallery URL has no links parameter")
            candidates = links[0].split(",")
        else:
            candidates = [line]
        for url in candidates:
            url = url.strip()
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.hostname != "carto.vietnamica.online":
                raise ValueError("Expected an HTTPS image URL on carto.vietnamica.online")
            if parts.query or parts.fragment or parts.username or parts.password:
                raise ValueError("Direct image URL must not contain query parameters or credentials")
            match = re.fullmatch(r"(\d{5})(?:-[\w-]+)?\.(jpg|jpeg|png)", Path(parts.path).name, re.I)
            if not match:
                raise ValueError("Cannot identify image reference number in URL filename")
            if url not in seen:
                seen.add(url)
                yield match[1], url, match[2].lower()


def download(url, target):
    partial = target.with_suffix(target.suffix + ".part")
    try:
        request = Request(url, headers={"User-Agent": "VanBia-course-downloader/1.0"})
        with urlopen(request, timeout=90) as response:
            if not response.headers.get_content_type().startswith("image/"):
                raise ValueError("Server did not return an image")
            expected = response.headers.get("Content-Length")
            with partial.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
        if expected is not None and partial.stat().st_size != int(expected):
            raise ValueError("Incomplete download")
        with partial.open("rb") as stream:
            signature = stream.read(8)
        valid = signature.startswith(b"\xff\xd8\xff") if target.suffix in (".jpg", ".jpeg") else signature == b"\x89PNG\r\n\x1a\n"
        if not valid:
            raise ValueError("Image signature does not match filename extension")
        # Exclusive creation: never overwrite the user's existing original.
        with target.open("xb") as output, partial.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
    finally:
        partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links-file", type=Path, default=ROOT / "data/metadata/vietnamica_links.txt")
    parser.add_argument("--output", type=Path, default=ROOT / "data/raw/anh_bia")
    parser.add_argument("--log", type=Path, default=ROOT / "data/metadata/download_log.csv")
    parser.add_argument("--dry-run", action="store_true", help="List image URLs without downloading or writing files")
    args = parser.parse_args()
    try:
        images = list(image_links(args.links_file.read_text(encoding="utf-8-sig").splitlines()))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    # If a reference has multiple different images, preserve source filenames.
    counts = {}
    for ref, _, _ in images:
        counts[ref] = counts.get(ref, 0) + 1
    failures = 0
    if not args.dry_run:
        args.output.mkdir(parents=True, exist_ok=True)
        args.log.parent.mkdir(parents=True, exist_ok=True)
    for ref, url, ext in images:
        filename = f"{ref}.{ext}" if counts[ref] == 1 else Path(urlsplit(url).path).name
        target = args.output / filename
        if args.dry_run:
            print(f"{filename} <- {url}")
            continue
        error_text = ""
        if target.exists():
            status = "exists_unverified"
        else:
            try:
                download(url, target)
                status = "downloaded"
            except Exception as error:
                status = "failed"
                error_text = str(error)
                failures += 1
            time.sleep(1)
        print(f"{ref}: {status}" + (f" ({error_text})" if error_text else ""))
        header = not args.log.exists() or args.log.stat().st_size == 0
        with args.log.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            if header:
                writer.writerow(["time_utc", "ref_number", "file", "source_url", "status", "error"])
            writer.writerow([datetime.now(timezone.utc).isoformat(), ref, str(target), url, status, error_text])
    print(f"Images listed: {len(images)}; failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
