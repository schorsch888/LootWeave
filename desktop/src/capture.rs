//! Explicit region capture using native GDI; no game process or memory access.
use base64::Engine;
use serde_json::{json, Value};
use windows_sys::Win32::Graphics::Gdi::*;
use windows_sys::Win32::UI::WindowsAndMessaging::*;

struct Resources {
    screen: HDC,
    memory: HDC,
    bitmap: HBITMAP,
    old: HGDIOBJ,
}
impl Drop for Resources {
    fn drop(&mut self) {
        unsafe {
            if !self.old.is_null() {
                SelectObject(self.memory, self.old);
            }
            if !self.bitmap.is_null() {
                DeleteObject(self.bitmap);
            }
            if !self.memory.is_null() {
                DeleteDC(self.memory);
            }
            if !self.screen.is_null() {
                ReleaseDC(std::ptr::null_mut(), self.screen);
            }
        }
    }
}

pub fn region(x: i32, y: i32, width: i32, height: i32) -> Result<Value, &'static str> {
    if width <= 0 || width > 1600 || height <= 0 || height > 1200 {
        return Err("region_size_exceeded");
    }
    unsafe {
        let left = GetSystemMetrics(SM_XVIRTUALSCREEN);
        let top = GetSystemMetrics(SM_YVIRTUALSCREEN);
        let right = left as i64 + GetSystemMetrics(SM_CXVIRTUALSCREEN) as i64;
        let bottom = top as i64 + GetSystemMetrics(SM_CYVIRTUALSCREEN) as i64;
        if x < left
            || y < top
            || x as i64 + width as i64 > right
            || y as i64 + height as i64 > bottom
        {
            return Err("region_outside_screen");
        }
        let mut r = Resources {
            screen: GetDC(std::ptr::null_mut()),
            memory: std::ptr::null_mut(),
            bitmap: std::ptr::null_mut(),
            old: std::ptr::null_mut(),
        };
        if r.screen.is_null() {
            return Err("capture_unavailable");
        }
        r.memory = CreateCompatibleDC(r.screen);
        if r.memory.is_null() {
            return Err("capture_unavailable");
        }
        r.bitmap = CreateCompatibleBitmap(r.screen, width, height);
        if r.bitmap.is_null() {
            return Err("capture_unavailable");
        }
        r.old = SelectObject(r.memory, r.bitmap);
        if r.old.is_null() || r.old as isize == -1 {
            r.old = std::ptr::null_mut();
            return Err("capture_unavailable");
        }
        if BitBlt(
            r.memory,
            0,
            0,
            width,
            height,
            r.screen,
            x,
            y,
            SRCCOPY | CAPTUREBLT,
        ) == 0
        {
            return Err("capture_failed");
        }
        SelectObject(r.memory, r.old);
        r.old = std::ptr::null_mut();
        let stride = ((width * 24 + 31) / 32 * 4) as usize;
        let size = stride * height as usize;
        let mut pixels = vec![0u8; size];
        let mut info: BITMAPINFO = std::mem::zeroed();
        info.bmiHeader.biSize = std::mem::size_of::<BITMAPINFOHEADER>() as u32;
        info.bmiHeader.biWidth = width;
        info.bmiHeader.biHeight = -height;
        info.bmiHeader.biPlanes = 1;
        info.bmiHeader.biBitCount = 24;
        info.bmiHeader.biCompression = BI_RGB;
        if GetDIBits(
            r.memory,
            r.bitmap,
            0,
            height as u32,
            pixels.as_mut_ptr() as _,
            &mut info,
            DIB_RGB_COLORS,
        ) != height
        {
            return Err("capture_failed");
        }
        let mut bmp = Vec::with_capacity(size + 54);
        bmp.extend_from_slice(b"BM");
        bmp.extend_from_slice(&((size + 54) as u32).to_le_bytes());
        bmp.extend_from_slice(&[0u8; 4]);
        bmp.extend_from_slice(&54u32.to_le_bytes());
        bmp.extend_from_slice(&40u32.to_le_bytes());
        bmp.extend_from_slice(&width.to_le_bytes());
        bmp.extend_from_slice(&(-height).to_le_bytes());
        bmp.extend_from_slice(&1u16.to_le_bytes());
        bmp.extend_from_slice(&24u16.to_le_bytes());
        bmp.extend_from_slice(&0u32.to_le_bytes());
        bmp.extend_from_slice(&(size as u32).to_le_bytes());
        bmp.extend_from_slice(&[0u8; 16]);
        bmp.extend_from_slice(&pixels);
        Ok(
            json!({"image_base64": base64::engine::general_purpose::STANDARD.encode(bmp),
                  "bounds": {"x": x, "y": y, "width": width, "height": height}}),
        )
    }
}
