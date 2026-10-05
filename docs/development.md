# Development guide

This guide covers repository checks and the experimental local source. Real-game recommendations and a production Windows release remain unaccepted. Read the [README](../README.md) for scope, the [implementation](implementation.md) for contracts, and the [validation record](validation.md) for measured results.

Run commands from the repository root. Dependency installation needs network access; subsequent checks may also need the platform capabilities listed below. No game installation is needed for the synthetic development workflow.

Pure source editing does not require local Windows packaging or Rust compilation. The [CI workflow](../.github/workflows/checks.yml) provides Windows build/check and preview artifacts; use the prerequisites below for the components you run locally.

## Prerequisites

| Work | Requirements |
| --- | --- |
| Documentation and portable Python checks | Git and Python 3.12 or newer |
| Browser development workflow | Above, plus Node.js 24 or newer and pnpm 11.19.0 |
| Native capture and OCR | Windows x64; installed Windows OCR language capabilities |
| Desktop build | Windows x64, 64-bit Python, frontend toolchain, Rust Windows MSVC toolchain, Microsoft C++ Build Tools, and the pinned Python build dependencies |
| Native WebView checks | A matching desktop build and Microsoft Edge WebView2 Runtime |
| Game-source research | Separate lawful inputs and external tools described in the [research guide](research.md) |

Python services use the standard library at runtime. The frontend pins its package manager and dependencies in [package.json](../frontend/package.json) and [pnpm-lock.yaml](../frontend/pnpm-lock.yaml); Rust dependencies are locked in [Cargo.lock](../desktop/Cargo.lock). The [CI workflow](../.github/workflows/checks.yml) records its toolchain, including Rust 1.94.1. These are reproducibility inputs, not a claim that all newer versions or platforms have passed acceptance.

For desktop system dependencies, follow the official [Tauri Windows prerequisites](https://v2.tauri.app/start/prerequisites/#windows), including the C++ desktop workload, Windows SDK, and WebView2.

## Run the experimental source

Install the pinned package manager if it is not already available:

```powershell
npm install --global pnpm@11.19.0 --ignore-scripts
```

Install the locked frontend dependencies, build, and launch:

```powershell
pnpm --dir frontend install --frozen-lockfile --ignore-scripts
pnpm --dir frontend build
python runtime.py --data-dir .local/development
```

The launcher starts local services, prints `Local UI ready at …`, and opens an authenticated browser session. It uses an ephemeral loopback port. Keep that terminal open, then use **Ctrl+C** to stop the launcher and its workers; closing the browser alone does not stop them.

Rust owns native capture, the desktop entry, and process lifecycle.
Python owns business APIs, statistics, and storage. The Windows package keeps one Rust EXE entry point with bundled Python services.

This example stores development data in the ignored `.local/development` directory. Without `--data-dir`, the default is `.local`. Retain the same directory to reopen saved profiles. The browser URL's session fragment is a credential and must not be shared.

On a fresh data directory, the workbench starts with a blank profile. Record item/build facts, review observations, confirm a snapshot, and save/reopen it. Adding an item to inventory does not equip it automatically. Use the fictional example to explore executable mechanisms; Deskrawl rules remain research-only, so unknown mechanics must remain blocked or pending confirmation. Record reviewed resource balances and preparation quotes to explore future-plan cost and budget gaps. These projections do not change actual equipment. Raw item-field differences do not establish DPS or an upgrade.

The browser workflow does not provide the Tauri host's native capture commands. Windows capture needs the desktop host. OCR uses installed `en-US` and `zh-Hans-CN` language capabilities; missing models or failed recognition leave manual entry and confirmation available. The current OCR adapter recognizes three generic demonstration labels: level, vitality, and armor.

### Send a live observation

LootWeave accepts observations with its `lootweave-live/1` protocol.
The workbench can load a JSON observation file.
The local sender posts a file through the existing Gateway to `/api/profile/live/samples`.

Start LootWeave.
Open the Live API panel.
Wait until Profile is ready.
Use the startup address printed by the launcher.
Set `LOOTWEAVE_LIVE_SESSION` to the current local session credential in your shell.
Then send a JSON file:

```powershell
python scripts/send_live_sample.py --gateway "<startup-address>" --file "<own-sample.json>"
```

Replace each placeholder with your startup address or JSON file path.
Do not share the session credential.
Sample publication and refresh do not confirm facts or create revisions.
The API stores source samples in memory. A draft freezes a preview.
Explicit confirmation creates a snapshot revision.

See the [owned API input](implementation.md#owned-live-api-input), [API protocol](live-api.md), and [feature coverage](live-feature-coverage.md).

Captured observations are saved before review. Accept or ignore each raw-text line and unmatched parsed field, map accepted rows to known/custom affixes, and review values and units. Confirm required level separately, then apply all reviewed rows to the candidate before confirming and saving the snapshot. A new capture requires a new review; duplicate targets block application. See the [OCR contract](implementation.md#ocr-behavior) for provenance and persistence guarantees.

### Startup policy

The default is `eager`. The explicit development experiment can be launched with:

```powershell
python runtime.py --data-dir .local/development-on-demand --startup-policy on-demand
```

This mode serves the shell before core readiness and activates OCR/Planning when needed. It failed the predeclared startup-latency comparison, so default promotion remains deferred. See the [performance results](performance-results.md); these observations do not establish visible cold-start or release acceptance.

## Build the Windows desktop

First complete the frontend setup above and install the desktop prerequisites. Then:

```powershell
python -m pip install -r requirements-build.txt
pnpm --dir frontend build
python scripts/build_desktop.py --installer
```

The script generates the icon, creates a PyInstaller directory bundle with embedded Python and notices, fetches locked Rust dependencies, and builds the Tauri/NSIS installer. It configures an offline WebView2 installer component. Dependency and packaging downloads still require network access on the builder.

Build outputs are local and ignored: the sidecar is under `dist/sidecar`, the release host is `desktop/target/release/lootweave-desktop.exe`, and NSIS output is under `desktop/target/release/bundle/nsis`. Dated installer copies in historical records are not files supplied by a clone.

| Option | Purpose |
| --- | --- |
| No option | Build the sidecar and release Rust host without an installer |
| `--sidecar-only` | Bundle Python without compiling Rust |
| `--debug` | Build a debug host |
| `--installer` | Build the desktop installer |
| `--test-native` | Run release Rust tests after generating matching build resources; use as a separate invocation |

A built installer is not release acceptance. Visible GUI, real-game capture, standard-user offline installation/removal on two clean Windows environments, and the other [M4 gates](roadmap.md#m4-one-entry-exe-and-local-lifecycle) require their own evidence.

### Portable Windows ZIP

Build the frontend and run `python scripts/build_desktop.py` to produce the frozen services and Rust host. Download and verify the official x64 CAB pinned in `scripts/webview-runtime.json`, expand all files, and package its named runtime directory:

~~~powershell
$sourceCommit = git rev-parse HEAD
$webviewPin = Get-Content scripts/webview-runtime.json -Raw | ConvertFrom-Json
$portableBuild = Join-Path (Get-Location).Path '.local/portable-runtime'
New-Item -ItemType Directory -Path $portableBuild -Force | Out-Null
$webviewCab = Join-Path $portableBuild 'webview2-fixed.cab'
Invoke-WebRequest -Uri $webviewPin.url -OutFile $webviewCab
if ((Get-FileHash $webviewCab -Algorithm SHA256).Hash.ToLowerInvariant() -ne $webviewPin.sha256) { throw 'fixed_webview_download_hash_mismatch' }
$expandedRuntime = Join-Path $portableBuild 'expanded'
New-Item -ItemType Directory -Path $expandedRuntime -Force | Out-Null
& "$env:SystemRoot/System32/expand.exe" $webviewCab '-F:*' $expandedRuntime | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'fixed_webview_expand_failed' }
$runtimeFolder = Join-Path $expandedRuntime ('Microsoft.WebView2.FixedVersionRuntime.' + $webviewPin.version + '.x64')
# Set this to the x64 Microsoft.VC*.CRT folder shipped in Visual Studio VC/Redist/MSVC.
$vcRuntime = '<Visual Studio x64 redistributable CRT directory>'
python scripts/build_portable.py --executable desktop/target/release/lootweave-desktop.exe --webview-runtime $runtimeFolder --vc-runtime-dir $vcRuntime --output dist/LootWeave-portable-windows-x64.zip --source-commit $sourceCommit
python scripts/check_portable_desktop.py --archive dist/LootWeave-portable-windows-x64.zip --report .local/portable-report.json
~~~

The package also copies `vcruntime140.dll` and `vcruntime140_1.dll` from Visual Studio's x64 redistributable folder beside both executables; these DLLs are required by the current Rust host. Their hashes join the portable and sidecar manifests. See Microsoft's [application-local C++ deployment guidance](https://learn.microsoft.com/en-us/cpp/windows/choosing-a-deployment-method?view=msvc-170).

When built, the portable ZIP packages `LootWeave.exe`, embedded Python, the fixed WebView2 runtime, application-local C++ runtime DLLs, and a `portable.json` marker. Extract it to a writable local directory and double-click `LootWeave.exe`; no application install or administrator rights are needed. The marker selects sibling `sidecar/`, `webview2/`, and `data/` folders, which keep SQLite, OCR captures, and browser data beside the app. Exit LootWeave before moving the folder. Upgrades replace app/runtime files while preserving `data/`; the regular installer continues to use `%LOCALAPPDATA%/LootWeave`. This describes packaging behavior, not portable acceptance evidence.

## Validate a change

### Required repository baseline

```powershell
python -m unittest discover -s tests -v
python scripts/check_public_docs.py
python -m compileall -q scripts
```

These commands require neither game files nor a compiled frontend. Platform-specific cases report skips when prerequisites are absent; inspect the final test summary. The publication checker inspects tracked and non-ignored untracked candidates and local link targets. It does not verify remote URLs, heading anchors, publication rights, or the absence of every secret.

### Architecture and archived evidence

```powershell
python scripts/check_architecture.py
python scripts/validate_ocr_holdout.py
python scripts/validate_ocr_holdout.py --version v7
```

The OCR auditors check saved synthetic observations and frozen parser results. They do not perform a new native OCR measurement. Follow the [research guide](research.md) for game-source checks; missing matching inputs mean those checks were not performed.

### Frontend

After installing the locked frontend dependencies:

```powershell
pnpm --dir frontend build
pnpm --dir frontend check:core
pnpm --dir frontend check:confirmation
pnpm --dir frontend check:capture
pnpm --dir frontend check:acquisition
node scripts/check_evaluation_render.mjs
node scripts/check_frontend_runtime.mjs
```

For browser interaction checks, also install the pinned browser runtime:

```powershell
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend check:ui
pnpm --dir frontend check:live
```

Linux CI additionally installs browser system dependencies; see the [workflow](../.github/workflows/checks.yml). Direct component checks, browser interaction, and native desktop behavior have different scopes.

The live input check starts LootWeave's own runtime and uses fictional observations.
It tests sender and file input, ten views, refresh, frozen drafts, and explicit confirmation.
It does not start a game.

### Native Windows

The capture/window guard harness can run without a full Tauri build:

```powershell
cargo fetch --locked --target x86_64-pc-windows-msvc --manifest-path desktop/Cargo.toml
python scripts/check_window_guards.py
```

After building matching host, sidecar, and frontend resources, use:

```powershell
python scripts/build_desktop.py --test-native
python scripts/check_preparation_desktop.py --executable desktop/target/release/lootweave-desktop.exe --resources dist/sidecar --report .local/preparation-desktop-report.json
python scripts/check_desktop.py --cycles 20 --executable desktop/target/release/lootweave-desktop.exe
python scripts/check_native_ui.py --cycles 20 --executable desktop/target/release/lootweave-desktop.exe
```

The native UI harness uses hidden, non-focusable windows for passive DOM/IPC checks and is not distributed in the installer. It does not establish visible painting, keyboard accessibility, cold-GUI performance, or clean-machine acceptance. Do not use an older binary as evidence for changed source.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| `pnpm` is missing or has the wrong version | Install the pinned package manager above and check `pnpm --version` |
| `frontend_build_missing` | Run the frontend install/build steps from the repository root, then restart the launcher |
| `instance_already_running` | Stop the other instance using that data directory, or choose a separate development directory; do not delete an active lock |
| OCR is unavailable | Check the installed Windows language capabilities; continue with manual entry and confirmation |
| Capture controls are unavailable in the browser | Use the Windows desktop host for native capture; browser development covers the manual workflow |
| Real-game evaluation is blocked | Check the game scope and unresolved evidence; Deskrawl research packs intentionally contain no executable rules |
| A research validator cannot find its inputs | Follow the matching-build prerequisites in the research guide; a clone does not contain game resources or generated intermediates |

If a problem remains, report a minimal synthetic reproduction through [Issues](https://github.com/schorsch888/LootWeave/issues), following the [contribution guide](../CONTRIBUTING.md). Include commands, versions, sanitized error categories, actual results, and missing prerequisites.
