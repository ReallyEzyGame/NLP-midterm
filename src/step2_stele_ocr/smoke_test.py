"""Run OCR on one sample image or a folder of images using the Lab SinoNom API; save raw results, not training labels."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[2] if len(_HERE.parents) >= 3 else _HERE.parent
for _p in (str(ROOT), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from src.step2_stele_ocr.ocr_bia import (
        LabOCRClient,
        RateLimitConfig,
        resolve_input_images,
        run_sequential_nom_ocr,
    )
except ImportError:
    from ocr_bia import (  # type: ignore[no-redef]
        LabOCRClient,
        RateLimitConfig,
        resolve_input_images,
        run_sequential_nom_ocr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data/samples/general_ocr_002.png",
        help="Path to a single image file or a folder of images to OCR",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/interim/paddle_raw/smoke_test",
        help="Directory to store *_res.json and *_ocr_res_img.jpg",
    )
    parser.add_argument("--domain", default=None, help="SinoNom API domain (defaults to SN_DOMAIN env var)")
    parser.add_argument("--token", default=None, help="Bearer token (defaults to SN_TOKEN env var)")
    parser.add_argument("--force", action="store_true", help="Re-run OCR even if output JSON already exists")
    args = parser.parse_args(argv)

    try:
        image_paths = resolve_input_images(args.input)
    except (FileNotFoundError, ValueError) as err:
        parser.error(str(err))

    args.output.mkdir(parents=True, exist_ok=True)
    cfg = RateLimitConfig()

    run_sequential_nom_ocr(
        image_paths=image_paths,
        output_dir=args.output,
        engine="nom",
        variant="smoke_test",
        force=args.force,
        ve_anh=True,
        config=cfg,
        client_factory=lambda: LabOCRClient(domain=args.domain, token=args.token),
    )

    total = 0
    for img_path in image_paths:
        res_file = args.output / f"{img_path.stem}_res.json"
        if not res_file.is_file():
            continue
        data = json.loads(res_file.read_text(encoding="utf-8"))
        texts = data.get("rec_texts", [])
        scores = data.get("rec_scores", [])
        total += len(texts)
        for text, score in zip(texts, scores):
            print(f"{float(score):.3f}\t{text}")

    print(f"Recognized text regions: {total}")
    print(f"Output: {args.output.resolve()}")
    if total == 0:
        raise SystemExit("No text recognized. Inspect the input image and output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())