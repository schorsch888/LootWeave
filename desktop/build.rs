fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "capture_region",
            "detect_deskrawl_windows",
            "capture_deskrawl_region",
        ]),
    ))
    .expect("desktop_build_failed");
}
