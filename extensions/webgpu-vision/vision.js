/* WebGPU image primitives — grayscale and Sobel edge map as real compute
 * shaders over storage buffers. No CDN, no npm, no network: pixels go from a
 * local <canvas> into a GPU buffer and back. Feature-detects navigator.gpu;
 * when WebGPU is unavailable the page says so (the perceptual hash in
 * ahash.js is CPU JavaScript and keeps working regardless).
 *
 * Scope is honest: these are hand-written image ops (luma, 3x3 convolution),
 * not a neural network. Nothing here classifies or recognises anything.
 */
"use strict";

const WGSL = /* wgsl */ `
struct Dims { w: u32, h: u32 };
@group(0) @binding(0) var<uniform> dims: Dims;
@group(0) @binding(1) var<storage, read> src: array<u32>;
@group(0) @binding(2) var<storage, read_write> dst: array<u32>;

// Integer luma (x1000), same weights as ahash.js / perceptual_hash.py.
fn lum(p: u32) -> u32 {
  let r = p & 0xffu;
  let g = (p >> 8u) & 0xffu;
  let b = (p >> 16u) & 0xffu;
  return (r * 299u + g * 587u + b * 114u) / 1000u;
}

fn pack_gray(p: u32, y: u32) -> u32 {
  return (p & 0xff000000u) | (y << 16u) | (y << 8u) | y;
}

@compute @workgroup_size(64)
fn grayscale(@builtin(global_invocation_id) gid: vec3<u32>) {
  let i = gid.x;
  if (i >= dims.w * dims.h) { return; }
  dst[i] = pack_gray(src[i], lum(src[i]));
}

// Luma of the pixel at (x, y), clamped at the edges.
fn lum_at(x: i32, y: i32) -> i32 {
  let cx = u32(clamp(x, 0, i32(dims.w) - 1));
  let cy = u32(clamp(y, 0, i32(dims.h) - 1));
  return i32(lum(src[cy * dims.w + cx]));
}

@compute @workgroup_size(8, 8)
fn sobel(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x >= dims.w || gid.y >= dims.h) { return; }
  let x = i32(gid.x);
  let y = i32(gid.y);
  let gx = -lum_at(x - 1, y - 1) + lum_at(x + 1, y - 1)
           - 2 * lum_at(x - 1, y) + 2 * lum_at(x + 1, y)
           - lum_at(x - 1, y + 1) + lum_at(x + 1, y + 1);
  let gy = -lum_at(x - 1, y - 1) - 2 * lum_at(x, y - 1) - lum_at(x + 1, y - 1)
           + lum_at(x - 1, y + 1) + 2 * lum_at(x, y + 1) + lum_at(x + 1, y + 1);
  let m = u32(clamp(abs(gx) + abs(gy), 0, 255));
  dst[gid.y * dims.w + gid.x] = pack_gray(src[gid.y * dims.w + gid.x], m);
}
`;

/** null when WebGPU is unavailable (no navigator.gpu or no adapter). */
async function initWebGPU() {
  if (!("gpu" in navigator)) return null;
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) return null;
  const device = await adapter.requestDevice();
  return { device, module: device.createShaderModule({ code: WGSL }) };
}

/**
 * Run one compute pass ("grayscale" | "sobel") over RGBA pixels.
 * @returns {Promise<Uint8ClampedArray>} processed RGBA, same dimensions.
 */
async function runOp(gpu, entryPoint, rgba, width, height) {
  const { device, module } = gpu;
  const n = width * height;
  const bytes = n * 4;

  const dimsBuf = device.createBuffer({
    size: 8, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  });
  device.queue.writeBuffer(dimsBuf, 0, new Uint32Array([width, height]));

  const srcBuf = device.createBuffer({
    size: bytes, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
  });
  device.queue.writeBuffer(srcBuf, 0, new Uint32Array(rgba.buffer, rgba.byteOffset, n));

  const dstBuf = device.createBuffer({
    size: bytes, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC,
  });
  const readBuf = device.createBuffer({
    size: bytes, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST,
  });

  const pipeline = device.createComputePipeline({
    layout: "auto", compute: { module, entryPoint },
  });
  const bind = device.createBindGroup({
    layout: pipeline.getBindGroupLayout(0),
    entries: [
      { binding: 0, resource: { buffer: dimsBuf } },
      { binding: 1, resource: { buffer: srcBuf } },
      { binding: 2, resource: { buffer: dstBuf } },
    ],
  });

  const enc = device.createCommandEncoder();
  const pass = enc.beginComputePass();
  pass.setPipeline(pipeline);
  pass.setBindGroup(0, bind);
  if (entryPoint === "grayscale") {
    pass.dispatchWorkgroups(Math.ceil(n / 64));
  } else {
    pass.dispatchWorkgroups(Math.ceil(width / 8), Math.ceil(height / 8));
  }
  pass.end();
  enc.copyBufferToBuffer(dstBuf, 0, readBuf, 0, bytes);
  device.queue.submit([enc.finish()]);

  await readBuf.mapAsync(GPUMapMode.READ);
  const out = new Uint8ClampedArray(readBuf.getMappedRange().slice(0));
  readBuf.unmap();
  [dimsBuf, srcBuf, dstBuf, readBuf].forEach((b) => b.destroy());
  return out;
}

globalThis.Vision = { initWebGPU, runOp };
