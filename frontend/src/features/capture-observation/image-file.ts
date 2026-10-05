// Validate transport pixels only; OCR and field interpretation remain in Python.
export class ImageFileError extends Error {}

export async function readBmpFile(file: Pick<File, "size" | "arrayBuffer">) {
  const limit = 6 * 1024 * 1024;
  if (file.size < 54 || file.size > limit) throw new ImageFileError("请选择不超过 6 MiB 的 BMP 截图。");
  const buffer = await file.arrayBuffer();
  if (buffer.byteLength !== file.size) throw new ImageFileError("截图文件大小发生变化，请重新选择。");
  const data = new DataView(buffer);
  const width = data.getInt32(18, true), height = data.getInt32(22, true);
  const bits = data.getUint16(28, true), offset = data.getUint32(10, true);
  if (data.getUint16(0, true) !== 0x4d42 || data.getUint32(14, true) !== 40
    || data.getUint16(26, true) !== 1 || ![24, 32].includes(bits) || data.getUint32(30, true) !== 0)
    throw new ImageFileError("当前支持未压缩的 24／32 位 BMP 截图。");
  if (width <= 0 || width > 1600 || height === 0 || Math.abs(height) > 1200)
    throw new ImageFileError("截图需要在 1600 × 1200 像素以内。请先裁剪需要核对的区域。");
  const required = Math.floor((width * bits + 31) / 32) * 4 * Math.abs(height);
  if (offset < 54 || offset + required > buffer.byteLength)
    throw new ImageFileError("截图像素不完整，请重新导出 BMP 文件。");
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let start = 0; start < bytes.length; start += 4096)
    binary += String.fromCharCode(...bytes.subarray(start, start + 4096));
  return { image_base64: btoa(binary), bounds: { x: 0, y: 0, width, height: Math.abs(height) } };
}
