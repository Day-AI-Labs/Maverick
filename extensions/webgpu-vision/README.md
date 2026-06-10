# WebGPU local vision primitives

A self-contained static page (no CDN, no npm, no build step) providing
GPU-accelerated image primitives plus cross-language perceptual hashing.

## What it is — and is not

**Is:** hand-written image operations that are genuinely implementable without
model weights:

- **Grayscale** — WGSL compute shader (integer luma, storage buffers).
- **Sobel edge map** — WGSL compute shader (3x3 convolution, clamp-at-edge).
- **8x8 average-hash** — perceptual hash for "are these two screenshots the
  same screen?" comparisons, with Hamming distance. CPU JavaScript
  (`ahash.js`), bit-identical to `maverick.perceptual_hash` on the Python
  side: both implementations are integer-only and both assert the same
  constant (`000001071f7fffff`) over a shared synthetic gradient.

**Is not:** a trained vision model. There is no classification, OCR, object
detection, or captioning here — that requires hardware plus model weights
this repository does not ship. The hash knows luminance layout, nothing more.

## Privacy

Images are chosen from the local disk and processed entirely inside the page
(GPU via WebGPU, or CPU for hashing). The page makes **zero network
requests**; nothing is uploaded anywhere.

## Running

Open `index.html` directly in a WebGPU-capable browser (Chrome/Edge 113+,
recent Firefox/Safari), or serve the folder locally:

    python3 -m http.server 8401 --bind 127.0.0.1

Without WebGPU the page degrades honestly: GPU buttons disable with a notice;
hashing keeps working (it is plain JavaScript).

## Cross-language guarantee

`node ahash.js --selftest` prints the gradient hash and exits non-zero on
mismatch. `packages/maverick-core/tests/test_perceptual_hash.py` asserts the
same constant from Python — and, when `node` is on PATH, runs the JS
self-test and compares outputs directly.
