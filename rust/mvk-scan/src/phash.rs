//! Perceptual image hashing — 8x8 average-hash + Hamming distance.
//!
//! A byte-for-byte port of `maverick.perceptual_hash`: it answers "are these
//! two screenshots the same screen?" without a vision model. The algorithm is
//! specified in **integer arithmetic only** so this Rust path, the pure-Python
//! fallback, and the JavaScript twin (`extensions/webgpu-vision/ahash.js`) all
//! produce bit-identical hashes — no float rounding can diverge across
//! languages.
//!
//!   1. gray(p) = r*299 + g*587 + b*114                (luma x1000, exact int)
//!   2. cells   = 8x8 grid; cell (cx, cy) covers x in [cx*w/8, (cx+1)*w/8)
//!   3. bit     = 1 iff cell_sum * total_count > total_sum * cell_count
//!                (cross-multiplied average comparison; ties are 0)
//!   4. pack    = row-major (cy outer), MSB first; render as 16 hex chars
//!
//! The cross-multiplication is done in `i128` so it never overflows for any
//! realistic image, matching Python's arbitrary-precision integers exactly.

/// 64-bit average-hash of row-major RGB `pixels`, as 16 lowercase hex chars.
///
/// `pixels` is a flat slice of `(r, g, b)` components in row-major order.
/// Returns `Err` with the SAME message as the Python `ValueError`s on a
/// dimension mismatch, so the shim can fall back without changing behaviour.
pub fn average_hash_from_pixels(
    pixels: &[(i64, i64, i64)],
    width: usize,
    height: usize,
) -> Result<String, String> {
    if width < 8 || height < 8 {
        return Err("image must be at least 8x8".to_string());
    }
    if pixels.len() != width * height {
        return Err(format!(
            "expected {} pixels, got {}",
            width * height,
            pixels.len()
        ));
    }
    let gray: Vec<i128> = pixels
        .iter()
        .map(|&(r, g, b)| r as i128 * 299 + g as i128 * 587 + b as i128 * 114)
        .collect();
    Ok(hash_gray(&gray, width, height))
}

/// Like [`average_hash_from_pixels`] but reads a contiguous row-major RGB byte
/// buffer (`[r, g, b, r, g, b, ...]`, length `width * height * 3`).
///
/// This is the real hot path: `PIL`'s `Image.tobytes()` hands us exactly this
/// buffer, so the whole image crosses the FFI boundary as one `bytes` object
/// instead of a million Python tuples — the per-pixel marshalling, not the luma
/// loop, was the cost. Bit-identical to the tuple API for 0..=255 components.
pub fn average_hash_from_rgb_bytes(
    rgb: &[u8],
    width: usize,
    height: usize,
) -> Result<String, String> {
    if width < 8 || height < 8 {
        return Err("image must be at least 8x8".to_string());
    }
    let expected = width.saturating_mul(height).saturating_mul(3);
    if rgb.len() != expected {
        return Err(format!("expected {} rgb bytes, got {}", expected, rgb.len()));
    }
    let gray: Vec<i128> = rgb
        .chunks_exact(3)
        .map(|c| c[0] as i128 * 299 + c[1] as i128 * 587 + c[2] as i128 * 114)
        .collect();
    Ok(hash_gray(&gray, width, height))
}

/// Shared core: the 8x8 cross-multiplied average comparison over a luma plane.
fn hash_gray(gray: &[i128], width: usize, height: usize) -> String {
    let total_sum: i128 = gray.iter().sum();
    let total_count = (width * height) as i128;
    let mut bits: u64 = 0;
    for cy in 0..8usize {
        let y0 = cy * height / 8;
        let y1 = (cy + 1) * height / 8;
        for cx in 0..8usize {
            let x0 = cx * width / 8;
            let x1 = (cx + 1) * width / 8;
            let mut cell_sum: i128 = 0;
            for y in y0..y1 {
                let row = y * width;
                for x in x0..x1 {
                    cell_sum += gray[row + x];
                }
            }
            let cell_count = ((y1 - y0) * (x1 - x0)) as i128;
            let bit = u64::from(cell_sum * total_count > total_sum * cell_count);
            bits = (bits << 1) | bit;
        }
    }
    format!("{bits:016x}")
}

/// Bit distance between two 16-hex-char hashes (0 identical .. 64 opposite).
///
/// Mirrors `perceptual_hash.hamming`: `Err` (same message) when either side is
/// not 16 hex chars, so the shim falls back to the Python `ValueError`.
pub fn hamming(a: &str, b: &str) -> Result<u32, String> {
    if a.chars().count() != 16 || b.chars().count() != 16 {
        return Err("hashes must be 16 hex chars (64 bits)".to_string());
    }
    let av = u64::from_str_radix(a, 16).map_err(|e| e.to_string())?;
    let bv = u64::from_str_radix(b, 16).map_err(|e| e.to_string())?;
    Ok((av ^ bv).count_ones())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The shared cross-language test image: a 64x64 two-axis RGB gradient.
    fn synthetic_gradient() -> Vec<(i64, i64, i64)> {
        let mut out = Vec::with_capacity(64 * 64);
        for y in 0..64i64 {
            for x in 0..64i64 {
                out.push((x * 4, y * 4, (x + y) * 2));
            }
        }
        out
    }

    #[test]
    fn gradient_hash_matches_python_and_js() {
        // Asserted identically in perceptual_hash.GRADIENT_HASH and ahash.js.
        let h = average_hash_from_pixels(&synthetic_gradient(), 64, 64).unwrap();
        assert_eq!(h, "000001071f7fffff");
    }

    #[test]
    fn rejects_small_or_mismatched() {
        assert!(average_hash_from_pixels(&[], 4, 4).is_err());
        assert_eq!(
            average_hash_from_pixels(&[(0, 0, 0)], 8, 8).unwrap_err(),
            "expected 64 pixels, got 1"
        );
    }

    #[test]
    fn bytes_path_matches_tuple_path() {
        let g = synthetic_gradient();
        let mut bytes = Vec::with_capacity(g.len() * 3);
        for &(r, gr, b) in &g {
            bytes.push(r as u8);
            bytes.push(gr as u8);
            bytes.push(b as u8);
        }
        let from_tuples = average_hash_from_pixels(&g, 64, 64).unwrap();
        let from_bytes = average_hash_from_rgb_bytes(&bytes, 64, 64).unwrap();
        assert_eq!(from_tuples, from_bytes);
        assert_eq!(from_bytes, "000001071f7fffff");
    }

    #[test]
    fn hamming_basics() {
        assert_eq!(hamming("0000000000000000", "0000000000000000").unwrap(), 0);
        assert_eq!(hamming("0000000000000000", "ffffffffffffffff").unwrap(), 64);
        assert_eq!(hamming("0000000000000000", "0000000000000001").unwrap(), 1);
        assert!(hamming("abc", "def").is_err());
    }
}
