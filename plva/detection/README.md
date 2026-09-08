# Local screenshot detection

`ScreenshotDetector.detect(png: bytes)` reads pixels through `LocalOCR`, then
classifies recognized text locally. It does not read the DOM, consume annotations,
preload expected private values, or call a remote inference service. Errors raise
instead of becoming an empty successful finding set. Whole OCR text-line regions
are used for masking; their axis-aligned boxes include a 3 px outward margin,
clamped to screenshot dimensions.

## Provisioning

On Windows x64 with Python 3.12:

```powershell
python -m pip install rapidocr-onnxruntime==1.4.4
python -m plva.detection.provision
```

The wheel supplies the detector and angle classifier. The explicit provisioning
command downloads a pinned English recognizer and dictionary and verifies their
SHA-256 hashes. Model construction and inference need no network connection, API
key, NVIDIA driver, or GPU. The wrapper explicitly disables CUDA and DirectML;
the measured runtime provider was `CPUExecutionProvider`. Models reside under
`rapidocr_onnxruntime/models` inside the installed Python site-packages directory
for detector/classifier; English assets reside in `~/.cache/plva/ocr`.
Missing or invalid English assets fail construction instead of silently falling
back to the bundled recognizer. The provision command is safe to rerun.
No model files or screenshots need to be committed. Shared requirements are
owned by the integration session and were not edited here.

Verified installed versions (not a replacement for the application's dependency
file):

```text
rapidocr-onnxruntime==1.4.4
onnxruntime==1.20.1
Pillow==12.3.0
numpy==2.5.1
opencv-python==5.0.0.93
pyclipper==1.4.0
shapely==2.1.2
PyYAML==6.0.3
six==1.17.0
tqdm==4.70.0
```

Bundled assets verified on 2026-09-08:

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `ch_PP-OCRv4_det_infer.onnx` | 4745517 | `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9` |
| `ch_PP-OCRv4_rec_infer.onnx` | 10857958 | `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b` |
| `ch_ppocr_mobile_v2.0_cls_infer.onnx` | 585532 | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |

Production additionally uses these assets from the inspected reference
`plvas-v3/models.lock.json`, pinned to RapidOCR v3.9.1 on ModelScope:

| Asset | SHA-256 |
| --- | --- |
| `en_PP-OCRv4_rec_mobile.onnx` (7653044 bytes) | `e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318` |
| `en_dict.txt` | `5662df9d2d03f0e8ca0d3b0649d6acbab904b6a14b3d3521463c71c37c668ce3` |

The full pinned URLs are in `provision.py`. The bundled Chinese/English
recognizer above remains installed but is not selected. The detector's SHA-256
is also identical to the reference. The reference's CoreML/Swift OCR
is unsuitable for this Windows CPU implementation.

## Measured coverage and limits

Initial measurements below used the bundled recognizer before the English
upgrade. A fresh Pillow-rendered 1100 x 420 screenshot using 28 px Arial contained six
lines: a heading, full name, email, phone, shipping street/city/state/ZIP address,
and a labelled API key. Actual ONNX inference recovered all six lines exactly,
including the unseen synthetic values. Model startup took 0.625 seconds and one
inference took 2.279 seconds with two CPU threads. These are a single-machine
sample, not a performance guarantee. Additional fresh 800 x 250 / 20 px and
1920 x 1080 / 16 px screenshots recovered email and phone regions. A blank PNG
returned no regions; malformed input raised `ValueError`.

One 16 px email read `lydia.ferm` instead of the rendered `lydia.fern` despite
0.933 OCR confidence. Classification can still mask its region as an email, but
the recovered vault value can be wrong. OCR-derived values require operator
review before relying on exact spelling. High recognition confidence is not a
privacy guarantee. Small text, unusual fonts, low contrast, crop boundaries,
images, handwriting, and unsupported scripts can cause misses. Images above
4096 px on their longest side are internally reduced by OCR before coordinates
are mapped back; small text may suffer. Names and addresses require visible
context or supported local patterns, not universal entity recognition. This is
a bounded hackathon detector, not proof that arbitrary websites contain no
unmasked private data.

## Regression evidence

Run from the repository root:

```powershell
python -m unittest discover -s tests -p test_privacy.py -v
$env:PLVA_TEST_OCR='1'
python -m unittest discover -s tests -p test_detection.py -v
```

Validated 2026-09-08: 14 privacy/classification tests passed (0.377s) and
6 detector tests passed (15.117s including actual model initialization/inference).
Without `PLVA_TEST_OCR=1`, CPU inference cases are explicitly skipped.
Fixtures are freshly rendered from pixels, including randomized email values,
16/22/28 px text at distinct screen offsets, multiline addresses, and a simulated
later scrolled viewport resized to 125% with its name/address labels removed.
Tests verify masking pixels are independent of the source content, value-free
metadata, coordinate bounds, repeated local discovery, invalid-image failure,
and revocation of usable aliases when a value is later classified as a secret.
The moved address test exposed OCR whitespace changes; repeat matching now
normalizes whitespace, including separately recognized multiline fragments.

These tests simulate scrolling and zoom in PNG fixtures; they are not live
Amazon or other website acceptance. Integration/verification owns those tests.
The session detector must be reused to preserve discovered-value matching.

Independent acceptance followup: the unchanged Session 5 PNG suite initially
passed 7/10 cases, with address, multiline address and phone failing exact-value
assertions because the bundled recognizer dropped spaces. Independent diagnostics
reported zero uncovered private glyph pixels in those three cases. The English
model now passes all 10 unchanged tests (17.354s), including exact normalized
values and all source glyph pixel coverage assertions. The oracle was copied
read-only and was not committed or altered by Session 3. This improves observed
transcription fidelity without implying perfect recognition on arbitrary pages.
