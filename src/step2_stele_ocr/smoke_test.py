"""Run OCR on one sample image; save raw results, not training labels."""

import argparse
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=root / "data/samples/general_ocr_002.png")
    parser.add_argument("--output", type=Path, default=root / "data/interim/paddle_raw/smoke_test")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"Image not found: {args.input}")

    from paddleocr import PaddleOCR

    args.output.mkdir(parents=True, exist_ok=True)
    ocr = PaddleOCR(
        lang="ch",
        device="cpu",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    total = 0
    for result in ocr.predict(str(args.input)):
        result.save_to_json(str(args.output))
        result.save_to_img(str(args.output))
        texts = result["rec_texts"]
        total += len(texts)
        for text, score in zip(texts, result["rec_scores"]):
            print(f"{float(score):.3f}\t{text}")
    print(f"Recognized text regions: {total}")
    print(f"Output: {args.output.resolve()}")
    if total == 0:
        raise SystemExit("No text recognized. Inspect the input image and output.")


if __name__ == "__main__":
    main()
