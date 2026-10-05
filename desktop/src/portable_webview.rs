use std::{marker::PhantomData, path::Path, rc::Rc, sync::mpsc};

use webview2_com::{
    CoreWebView2EnvironmentOptions, CreateCoreWebView2EnvironmentCompletedHandler,
    Microsoft::Web::WebView2::Win32::{
        CreateCoreWebView2EnvironmentWithOptions, ICoreWebView2Environment,
        ICoreWebView2EnvironmentOptions,
    },
};
use windows::{
    core::{Error, HSTRING},
    Win32::{
        Foundation::{E_POINTER, E_UNEXPECTED},
        Globalization::{
            GetUserDefaultUILanguage, LCIDToLocaleName, LOCALE_ALLOW_NEUTRAL_NAMES, MAX_LOCALE_NAME,
        },
        System::Com::{CoInitializeEx, CoUninitialize, COINIT_APARTMENTTHREADED},
    },
};

// Match Wry 0.55.1's default browser arguments with its default autoplay setting.
const DEFAULT_BROWSER_ARGS: &str = "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required";

pub struct StaApartment {
    // COM initialization and uninitialization must run on the same UI thread.
    _thread: PhantomData<Rc<()>>,
}

impl StaApartment {
    pub fn initialize() -> Result<Self, &'static str> {
        // Both S_OK and S_FALSE acquire a COM initialization reference.
        unsafe { CoInitializeEx(None, COINIT_APARTMENTTHREADED) }
            .ok()
            .map_err(|_| "portable_webview_com_initialization_failed")?;
        Ok(Self {
            _thread: PhantomData,
        })
    }
}

impl Drop for StaApartment {
    fn drop(&mut self) {
        // Balance only our initialization, after the application's WebViews close.
        unsafe { CoUninitialize() };
    }
}

pub fn create_environment(
    runtime: &Path,
    data: &Path,
    browser_args: Option<&str>,
) -> Result<ICoreWebView2Environment, &'static str> {
    let runtime = HSTRING::from(runtime);
    let data = HSTRING::from(data);
    let options = CoreWebView2EnvironmentOptions::default();
    unsafe {
        options.set_additional_browser_arguments(
            browser_args.unwrap_or(DEFAULT_BROWSER_ARGS).to_owned(),
        );
        // Preserve Wry's system-language choice when supplying its environment.
        let mut language = [0; MAX_LOCALE_NAME as usize];
        let length = LCIDToLocaleName(
            GetUserDefaultUILanguage() as u32,
            Some(&mut language),
            LOCALE_ALLOW_NEUTRAL_NAMES,
        );
        if length > 0 {
            options.set_language(String::from_utf16_lossy(&language[..length as usize - 1]));
        }
    }
    let options = ICoreWebView2EnvironmentOptions::from(options);
    let (sender, receiver) = mpsc::channel();
    let handler = CreateCoreWebView2EnvironmentCompletedHandler::create(Box::new(
        move |status, environment| {
            let result = status.and_then(|()| environment.ok_or_else(|| Error::from(E_POINTER)));
            sender.send(result).map_err(|_| Error::from(E_UNEXPECTED))
        },
    ));
    // The folder arguments are explicit API inputs, including when elevated.
    unsafe { CreateCoreWebView2EnvironmentWithOptions(&runtime, &data, &options, &handler) }
        .map_err(|_| "portable_webview_environment_failed")?;
    // WebView2 completes on this STA thread through its message queue. Blocking
    // recv() here would prevent the callback; use the same pump as Wry instead.
    webview2_com::wait_with_pump(receiver)
        .map_err(|_| "portable_webview_environment_failed")?
        .map_err(|_| "portable_webview_environment_failed")
}
