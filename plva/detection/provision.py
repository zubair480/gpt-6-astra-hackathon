"""Explicit, hash-verified installation of the portable English OCR assets.

Run ``python -m plva.detection.provision`` once before local inference.
Only this provisioning command uses the network; detection never downloads.
"""
from pathlib import Path
import hashlib
import urllib.request

MODEL_DIR = Path.home() / ".cache" / "plva" / "ocr"
ASSETS = (
    ("en_PP-OCRv4_rec_mobile.onnx",
     "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx",
     "e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318"),
    ("en_dict.txt",
     "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/paddle/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile/en_dict.txt",
     "5662df9d2d03f0e8ca0d3b0649d6acbab904b6a14b3d3521463c71c37c668ce3"),
)


def model_paths():
    paths = []
    for name, _, digest in ASSETS:
        path = MODEL_DIR / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("English OCR assets missing or invalid; run python -m plva.detection.provision")
        paths.append(str(path))
    return paths


def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, url, digest in ASSETS:
        path = MODEL_DIR / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError("Downloaded OCR asset failed integrity verification")
        path.write_bytes(data)
    model_paths()
    print("Verified local English OCR assets:", MODEL_DIR)


if __name__ == "__main__":
    main()
