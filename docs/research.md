# Research reproduction and validation

This repository publishes selected research records and read-only tools, not a desktop application or a game database. The commands below describe the existing toolchain for Deskrawl build `25690430`; they require lawfully available matching source files. A clone alone cannot reproduce game-source checks. Product status and future acceptance gates are in the [design](design.md) and [Roadmap](roadmap.md).

## Public evidence and boundaries

| Record | Purpose and limit |
| --- | --- |
| [Extraction validation](../research/extraction-validation.json) | Recorded object/byte/header/reference checks, eight sample relationships and independent serialized-number validation; partial historical stages are marked superseded. |
| [XP evidence](../research/experience-penalty.json) and [XP explanation](experience-penalty.md) | Reviewed native branches, constants, source identities and unknown server behavior; not measured route efficiency. |
| [Equipment/builds](../research/equipment-builds.json), [combat/progression](../research/combat-progression.json), [world/economy](../research/world-economy.json) | Versioned research sources, known mechanisms, limitations and fields needed for judgment; community claims retain their evidence level. |
| [Decision model](../research/decision-model.json), [loot planning](../research/loot-planning.json) | Proposed input/decision contracts and acquisition reasoning; these are not implemented product services. |
| [Toolchain provenance](../research/toolchain-provenance.json) | Pinned versions, official release identities and the recorded environment. |

The recorded local result is 1,593 selected objects, zero parse failures and 3,080 ObscuredFloat, 67 ObscuredInt and 196 ObscuredLong conversions independently checked. The readable catalog projects 817 definitions. These are historical measurements for the named inputs, not promises for another installation or proof of complete mechanics, DPS, actual inventory or final drop probabilities.

Game resources, full `data/extracted/` output, generated DLLs/types and downloaded `.tools/` stay local and ignored. Research does not read saves, inject code, access game memory/DMA, control gameplay or dispose of items. The project license does not authorize copying game resources or third-party software; their access, use and redistribution terms remain separate.

## Inspect the repository without game files

From the repository root, using Python 3.12:

```powershell
python scripts/check_public_docs.py
python scripts/extract_deskrawl.py --help
python scripts/validate_deskrawl_numeric.py --help
python scripts/validate_deskrawl_xp.py --help
```

These entry points exist in the public repository. Help and documentation checks use the standard library; passing them is not a source or gameplay verification result. Do not claim source verification when the matching game files are unavailable.

## Prepare the local research dependencies

The recorded setup is Windows x64, Python 3.12, PowerShell 7, Unity `6000.3.6f1` and IL2CPP metadata version 39. Other environments have not been accepted. [UnityPy 1.25.2](https://pypi.org/project/UnityPy/1.25.2/) and [TypeTreeGeneratorAPI 0.0.10](https://pypi.org/project/TypeTreeGeneratorAPI/0.0.10/) provide asset parsing and generated type trees; Python package versions are pinned in [requirements-research.txt](../requirements-research.txt). Their recorded transitive versions are pinned too, but this is not a hash-enforced cross-platform lock. Native wheel/runtime availability still needs validation on a fresh machine.

```powershell
python -m pip install --target .tools/unitypy -r requirements-research.txt
```

Prepare the official [Cpp2IL 2022.1.0-pre-release.21 Windows asset](https://github.com/SamboyCoding/Cpp2IL/releases/download/2022.1.0-pre-release.21/Cpp2IL-2022.1.0-pre-release.21-Windows.exe) as `.tools/cpp2il/Cpp2IL.exe`. The expected SHA-256 is `663fb432433b4371fd1ee0ebc321a8fff2a9aac5ac4230c843f9e03ddee4e04c`; it matches the recorded local executable and the [official release metadata](https://api.github.com/repos/SamboyCoding/Cpp2IL/releases/tags/2022.1.0-pre-release.21). No tool binary is distributed here.

```powershell
$Cpp2IL = '.tools/cpp2il/Cpp2IL.exe'
$Expected = '663fb432433b4371fd1ee0ebc321a8fff2a9aac5ac4230c843f9e03ddee4e04c'
if ((Get-FileHash -LiteralPath $Cpp2IL -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected) {
    throw 'Cpp2IL identity mismatch; stop.'
}
$GameDir = $env:DESKRAWL_GAME_DIR
if (-not $GameDir) { throw 'Set DESKRAWL_GAME_DIR to the matching game installation directory.' }
$Out = 'data/extracted/deskrawl/25690430'
```

`DESKRAWL_GAME_DIR` is a runtime input, not a committed personal path. Source records use `game://`, `repo://` and `steam://`; Steam state is used only for application/build identity, without installation activity times or an ACF file hash.

## Generate the missing type information locally

These commands match the three recorded Cpp2IL output passes. They analyze static IL2CPP inputs and generate local intermediate files; do not launch the game or execute its native methods.

```powershell
& $Cpp2IL --game-path "$GameDir" --exe-name Deskrawl --output-as dummydll --output-to .tools/cpp2il/deskrawl-25690430-dummy
& $Cpp2IL --game-path "$GameDir" --exe-name Deskrawl --output-as diffable-cs --output-to .tools/cpp2il/deskrawl-25690430-types
& $Cpp2IL --game-path "$GameDir" --exe-name Deskrawl --use-processor attributeinjector --output-as dll_default --output-to .tools/cpp2il/deskrawl-25690430-addresses
```

The extractor requires the dummy DLL folder, `DiffableCs` declarations and the address-bearing `ACTk.Runtime.dll`. It restores missing private fields and managed-reference registry v2 layouts, then uses the strict Python reader. Names and object counts alone do not prove a complete parse. Unsupported registry versions and mismatched native conversion bytes fail rather than silently accepting another build.

## Extract selected definitions and validate them

The required source inputs are four static files under `Deskrawl_Data`: `resources.assets`, `sharedassets0.assets`, `globalgamemanagers.assets` and `level0`, plus `GameAssembly.dll` and `Deskrawl_Data/il2cpp_data/Metadata/global-metadata.dat`. The extractor requires Steam build `25690430`. Use `--steam-manifest` if the application manifest is outside the usual Steam directory layout. All source inputs remain read-only; output is written under the ignored extraction directory.

```powershell
# Optional inventory: headers/classes are discovery, not complete field validation.
python scripts/inspect_deskrawl_assets.py --game "$GameDir" --out "$Out/inventory" --files resources.assets sharedassets0.assets globalgamemanagers.assets level0

python scripts/extract_deskrawl.py --game "$GameDir" --out "$Out" --dummy .tools/cpp2il/deskrawl-25690430-dummy --headers .tools/cpp2il/deskrawl-25690430-types/DiffableCs --address-dll .tools/cpp2il/deskrawl-25690430-addresses/ACTk.Runtime.dll
& ./scripts/extract_deskrawl_enums.ps1
python scripts/validate_deskrawl_numeric.py --game "$GameDir" --source-root "$Out" --report "$Out/validation.json"
python scripts/build_extraction_catalog.py --source-root "$Out" --output "$Out/catalog.json" --batch-status final
python scripts/validate_deskrawl_xp.py --game "$GameDir" --source-root "$Out"
```

The numeric validator writes a fresh local report, using the public validation record as its baseline; the example avoids overwriting the public record. The enum script defaults to these same ignored folders. Custom paths have corresponding CLI parameters; inspect help before using them.

Review each command's result. Extraction must report strict parse success, full byte counts and matching built-in headers; inspect class coverage, omitted classes, failed records and PPtr targets. Numeric validation independently traverses repaired type trees and managed types, matches every raw/derived numeric path, checks six native method byte sequences and PE address mappings, and re-encodes all values to their original bytes. It does not establish stat units or gameplay formulas. Catalog `final` is a caller-supplied label, not a passed validation gate: review failures and input hashes first.

The XP validator uses only the standard library. It checks reviewed source hashes, the formal GameManager configuration link, native method hashes, PE mappings and constants against public XP evidence. It verifies evidence identity, not a new semantic decompilation, behavioral experiment, server formula or best leveling map. Changed source hashes or generated inputs require review; never replace expected hashes merely to force a pass.

## Record outcomes and failures

Keep generated manifests, raw objects, local validation and catalog output ignored. A public result should state build, tool versions, immutable source hashes, scope, observed counts, failed checks and unknowns, with no host paths or real character snapshots. Keep the original evidence and record metadata revisions when privacy normalization changes a report; do not claim an altered artifact is byte-identical to the original.

The documentation update checked compilation, CLI help, pinned installed-package metadata and missing-game failure paths. It revalidated existing local exports with the numeric and XP validators, including creation of a new local report; it did not repeat the full extraction or install dependencies on a clean machine. A fresh-machine end-to-end run, full combat rules, live server overrides and measured acquisition/leveling efficiency remain outstanding. For publication checks, use [AGENTS.md](../AGENTS.md); for future product gates, use the [Roadmap](roadmap.md).
