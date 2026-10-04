# Research reproduction and validation

This repository contains a runnable local development implementation and Windows desktop source, alongside selected research records and read-only research tools; it is not a game database. The commands below describe the research toolchain for Deskrawl build `25690430`; they require lawfully available matching source files. A clone alone cannot reproduce game-source checks. Current product scope and acceptance gates are in the [implementation record](implementation.md), [design](design.md) and [Roadmap](roadmap.md).

## Public evidence and boundaries

| Record | Purpose and limit |
| --- | --- |
| [Extraction validation](../research/extraction-validation.json) | Recorded object/byte/header/reference checks, eight sample relationships and independent serialized-number validation; partial historical stages are marked superseded. |
| [XP evidence](../research/experience-penalty.json) and [XP explanation](experience-penalty.md) | Reviewed native branches, constants, source identities and unknown server behavior; not measured route efficiency. |
| [Equipment/builds](../research/equipment-builds.json), [combat/progression](../research/combat-progression.json), [world/economy](../research/world-economy.json) | Versioned research sources, known mechanisms, limitations and fields needed for judgment; community claims retain their evidence level. |
| [Frostwyrm trace](../research/deskrawl-frostwyrm.json) | Selected static/native evidence for Deskrawl build `25690430`: three strict objects, two links, one managed effect, 14 field layouts, two enum values and nine source-hashed native methods. No online validation or M1 acceptance. |
| [Frostwyrm lifecycle trace](../research/deskrawl-frostwyrm-lifecycle.json) | Separate selected trace: 12 source hashes, three strict objects, two links, one managed effect, 15 field layouts, two enums, 15 native methods, five direct relative links, one PE exception-directory function-bound check and a previous-record hash/scope check. It is not complete lifecycle or online validation. |
| [Frostwyrm method-slot metadata](../research/deskrawl-frostwyrm-method-slots.json) | Adds original metadata v39 checks for two types, four selected virtual method declarations and two concrete method-index targets to the selected lifecycle trace. The prior record stays unchanged. Native class layout, indirect dispatch and live equipment events remain unaccepted. |
| [Frostwyrm native module pointers](../research/deskrawl-frostwyrm-module-pointers.json) | Adds one original metadata image and two token-indexed x64 module entries that match the previously hashed concrete methods; no runtime registration/class-dispatch or live-equipment acceptance. |
| [Frostwyrm code registration](../research/deskrawl-frostwyrm-code-registration.json) | Adds a hashed x64 v39 registration tail, 95-entry module-array range, selected module entry and PE exception-bounded address reference. Native module index 6 differs from metadata image index 3; no executed registration, class-dispatch or gameplay acceptance. |
| [Decision model](../research/decision-model.json), [loot planning](../research/loot-planning.json) | Research input/decision contracts and acquisition reasoning. The local planning service records manually measured, scope-bound XP/time trials and checks prerequisites for the synthetic fixture; it is not a Deskrawl rules database or a live acquisition feed. |
| [Synthetic OCR holdout v6](../fixtures/ocr-critical-fields-v6/README.md) | Complete original 200-region/600-field renderer inputs, native observations and scores with byte-preserving sources; 200 exact local image reconstructions/parser replays. Historical 91.67% accuracy and pending independent human truth review leave M2 unaccepted. |
| [Toolchain provenance](../research/toolchain-provenance.json) | Pinned versions, official release identities and the recorded environment. |

The recorded local result is 1,593 selected objects, zero parse failures and 3,080 ObscuredFloat, 67 ObscuredInt and 196 ObscuredLong conversions independently checked. The readable catalog projects 817 definitions. These are historical measurements for the named inputs, not promises for another installation or proof of complete mechanics, DPS, actual inventory or final drop probabilities.

Game resources, full `data/extracted/` output, generated DLLs/types and downloaded `.tools/` stay local and ignored. Research does not read saves, inject code, access game memory/DMA, control gameplay or dispose of items. The project license does not authorize copying game resources or third-party software; their access, use and redistribution terms remain separate.

## Inspect the repository without game files

From the repository root, using Python 3.12:

```powershell
python scripts/check_public_docs.py
python scripts/validate_ocr_holdout.py
python scripts/extract_deskrawl.py --help
python scripts/validate_deskrawl_numeric.py --help
python scripts/validate_deskrawl_xp.py --help
python scripts/validate_deskrawl_frostwyrm.py --help
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

After extracting the matching installed build and generating the local field declarations, set `DESKRAWL_GAME_DIR` to the installed build directory and run the Frostwyrm identity checkers:

```powershell
if (-not $env:DESKRAWL_GAME_DIR) { throw 'Set DESKRAWL_GAME_DIR to the matching Deskrawl build 25690430 directory.' }
python scripts/validate_deskrawl_frostwyrm.py
python scripts/validate_deskrawl_frostwyrm.py --evidence research/deskrawl-frostwyrm-lifecycle.json
python scripts/validate_deskrawl_frostwyrm.py --evidence research/deskrawl-frostwyrm-method-slots.json
python scripts/validate_deskrawl_frostwyrm.py --evidence research/deskrawl-frostwyrm-module-pointers.json
python scripts/validate_deskrawl_frostwyrm.py --evidence research/deskrawl-frostwyrm-code-registration.json
```

All five invocations read the installed build and local extraction/type sources; they do not execute game code or write into them. The default checks the original record; the second selects the lifecycle record and additionally validates signed direct relative calls/tail jumps, PE exception-directory function bounds and prior-record hash/scope. Microsoft’s [x64 exception-handling documentation](https://learn.microsoft.com/en-us/cpp/build/exception-handling-x64) describes the primary PE exception-directory model used for the function-bound check. The third adds selected original metadata type/method declarations and concrete vtable method-index checks. It supports only metadata v39 with the recorded two-byte type/type-definition/generic indices and four-byte parameter indices; different versions or width/stride profiles fail. Header ranges, string boundaries, declaring types, method tokens/flags/parameter counts, slots and concrete targets are checked directly. The layouts and encoded method-index interpretation follow the pinned Cpp2IL [method definition](https://github.com/SamboyCoding/Cpp2IL/blob/2022.1.0-pre-release.21/LibCpp2IL/Metadata/Il2CppMethodDefinition.cs), [type definition](https://github.com/SamboyCoding/Cpp2IL/blob/2022.1.0-pre-release.21/LibCpp2IL/Metadata/Il2CppTypeDefinition.cs) and [metadata usage reader](https://github.com/SamboyCoding/Cpp2IL/blob/2022.1.0-pre-release.21/LibCpp2IL/MetadataUsage.cs).

The 0.4.0-research pack adds this metadata evidence only; its `rules` array remains empty. Versions 0.1.0-research through 0.4.0-research retain their original bytes/hashes, and all six explicit versions remain available. The selected declarations assign `bxz` and `bya` slots 4 and 5 in both types, and the concrete type's metadata entries point to its corresponding own methods. Native class vtable layout and pointer materialization are still unaccepted; slot metadata alone does not establish runtime dispatch, legal duplicates or every equip/unequip event. All validator outputs retain `online_validated=false` and `m1_accepted=false`.

The fourth invocation reads the selected original metadata image: image 3 names Assembly-CSharp.dll, and its type range contains both selected effect types. It checks the x64 module's 24-byte prefix, bounded null-terminated name, declared table pointer/count and complete file-backed table range. The two concrete tokens 0x06000493/0x06000494 select indices 1170/1171, and those entries match the already hashed bxz/bya bodies. The table declares 7,831 entries; only these two entries are selected evidence. All selected concrete declarations require a binding, and omitted, duplicate, abstract, out-of-range or mismatched bindings fail.

The image layout follows the pinned [Cpp2IL image definition](https://github.com/SamboyCoding/Cpp2IL/blob/2022.1.0-pre-release.21/LibCpp2IL/Metadata/Il2CppImageDefinition.cs). The module prefix and token-index lookup follow its [code-generation module reader](https://github.com/SamboyCoding/Cpp2IL/blob/2022.1.0-pre-release.21/LibCpp2IL/BinaryStructures/Il2CppCodeGenModule.cs) and [method-pointer reader](https://github.com/SamboyCoding/Cpp2IL/blob/2022.1.0-pre-release.21/LibCpp2IL/Il2CppBinary.cs). The selected ordinary static entries do not prove that a runtime registration root consumes this module, materializes a particular class vtable or dispatches either callback during gameplay. Generic/adjustor paths and all live change events remain unaccepted. The new 0.5.0-research pack has empty rules; rollback selects a prior explicit research version. Use the checker with the new image/module checks for this record: older checker versions do not validate these added sections.


The fifth invocation follows the build-specific x64 v39 layout in the pinned [Cpp2IL code-registration reader](https://github.com/SamboyCoding/Cpp2IL/blob/2022.1.0-pre-release.21/LibCpp2IL/BinaryStructures/Il2CppCodeRegistration.cs). It hashes all 136 bytes, checks the module count/pointer at offsets 120/128 and the full 95-entry array range, and verifies selected entry 6 points to the already checked Assembly-CSharp module. The original metadata table also declares 95 images, but its selected image index is 3: equality of table order is neither assumed nor required. A selected seven-byte RIP-relative LEA RCX encoding resolves to the registration RVA inside a hashed, PE exception-bounded body. No exported identity or full semantics are asserted for that body. Other registration fields/modules, executed registration, class-vtable materialization, generic/adjustor paths and live dispatch remain outside acceptance. The `0.6.0-research` pack keeps rules empty; versions 0.1–0.5 retain their original bytes. Use the current checker for these added sections: an older checker does not validate them.

The XP validator uses only the standard library. It checks reviewed source hashes, the formal GameManager configuration link, native method hashes, PE mappings and constants against public XP evidence. It verifies evidence identity, not a new semantic decompilation, behavioral experiment, server formula or best leveling map. Changed source hashes or generated inputs require review; never replace expected hashes merely to force a pass.

## Record outcomes and failures

Keep generated manifests, raw objects, local validation and catalog output ignored. A public result should state build, tool versions, immutable source hashes, scope, observed counts, failed checks and unknowns, with no host paths or real character snapshots. Keep the original evidence and record metadata revisions when privacy normalization changes a report; do not claim an altered artifact is byte-identical to the original.

The recorded research-documentation update checked compilation, CLI help, pinned installed-package metadata and missing-game failure paths. It revalidated existing local exports with the numeric and XP validators, including creation of a new local report; it did not repeat the full extraction or install dependencies on a clean machine. A fresh-machine end-to-end run, full combat rules, live server overrides and independently validated real-game acquisition/leveling efficiency remain outstanding. The product can record manual trials, but those entries alone do not establish game performance. For publication preflight, run `python scripts/check_public_docs.py`; measured product scopes are recorded in [validation](validation.md), with acceptance gates in the [Roadmap](roadmap.md).
