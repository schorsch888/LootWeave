param(
    [string]$Headers = '.tools/cpp2il/deskrawl-25690430-types/DiffableCs/Assembly-CSharp',
    [string]$DummyDll = '.tools/cpp2il/deskrawl-25690430-dummy/Assembly-CSharp.dll',
    [string]$Output = 'data/extracted/deskrawl/25690430/enums.json'
)
$ErrorActionPreference = 'Stop'
$taskRepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Resolve-RepoInput([string]$Value) {
    if ([IO.Path]::IsPathRooted($Value)) { return $Value }
    return Join-Path $taskRepoRoot $Value
}
function Get-SourceLabel([string]$Value) {
    $taskRelative = [IO.Path]::GetRelativePath($taskRepoRoot, [IO.Path]::GetFullPath($Value)).Replace('\', '/')
    if ($taskRelative -eq '..' -or $taskRelative.StartsWith('../')) { return 'external://headers/' + [IO.Path]::GetFileName($Value) }
    return 'repo://' + $taskRelative
}
$Headers = Resolve-RepoInput $Headers
$DummyDll = Resolve-RepoInput $DummyDll
$Output = Resolve-RepoInput $Output
$taskEnums = [ordered]@{}
$taskHeaderRoot = (Resolve-Path -LiteralPath $Headers).Path
foreach ($taskFile in Get-ChildItem -LiteralPath $taskHeaderRoot -File -Filter '*.cs' | Sort-Object Name) {
    $taskSource = Get-Content -LiteralPath $taskFile.FullName -Raw
    $taskMatch = [regex]::Match($taskSource, '(?s)^//Type is in global namespace\s+(?:\[Flags\]\s+)?public enum (?<name>\w+) : (?<base>\w+)\s*\{(?<body>.*?)\}')
    if (-not $taskMatch.Success) { continue }
    $taskMembers = [ordered]@{}
    foreach ($taskLine in $taskMatch.Groups['body'].Value -split '\r?\n') {
        if ([string]::IsNullOrWhiteSpace($taskLine)) { continue }
        $taskMember = [regex]::Match($taskLine, '^\s*(?<name>\w+)\s*=\s*(?<value>-?\d+),\s*$')
        if (-not $taskMember.Success) { throw "Unsupported enum declaration in $($taskFile.Name): $taskLine" }
        $taskMembers[$taskMember.Groups['name'].Value] = [long]::Parse($taskMember.Groups['value'].Value, [cultureinfo]::InvariantCulture)
    }
    if ($taskMembers.Count -eq 0) { throw "Empty enum in $($taskFile.Name)" }
    $taskName = $taskMatch.Groups['name'].Value
    if ($taskEnums.Contains($taskName)) { throw "Duplicate global enum: $taskName" }
    $taskEnums[$taskName] = [ordered]@{
        underlying_type = $taskMatch.Groups['base'].Value
        flags = [bool]($taskSource -match '\[Flags\]')
        members = $taskMembers
        source_file = Get-SourceLabel $taskFile.FullName
        source_sha256 = (Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
foreach ($taskRequired in 'StatType','ItemRarity','ItemType','AbilityTag','HeroClass','EquipSlotType','EquipSlotId') {
    if (-not $taskEnums.Contains($taskRequired)) { throw "Missing required enum: $taskRequired" }
}
$taskPayload = [ordered]@{
    schema_version = 1
    build_id = '25690430'
    extraction_kind = 'local_static_cpp2il_diffable_cs_global_game_enums'
    tool = 'Cpp2IL 2022.1.0-pre-release.21'
    source_headers_root = Get-SourceLabel $taskHeaderRoot
    dummy_assembly = Get-SourceLabel (Resolve-Path -LiteralPath $DummyDll).Path
    dummy_assembly_sha256 = (Get-FileHash -LiteralPath $DummyDll -Algorithm SHA256).Hash.ToLowerInvariant()
    scope = 'Assembly-CSharp global namespace public enums; vendor namespaces and nested enums excluded.'
    interpretation = 'Literal names and constant values from generated local types; no game code execution or community values. Flags, spelling, order and numeric gaps preserved. Does not prove runtime semantics.'
    enums = $taskEnums
}
$taskJson = $taskPayload | ConvertTo-Json -Depth 10
$taskAbsoluteOutput = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($taskAbsoluteOutput)) | Out-Null
[IO.File]::WriteAllText($taskAbsoluteOutput, $taskJson, [Text.UTF8Encoding]::new($false))
$taskValidated = Get-Content -LiteralPath $taskAbsoluteOutput -Raw | ConvertFrom-Json
[pscustomobject]@{ output=(Get-SourceLabel $taskAbsoluteOutput); enum_count=$taskEnums.Count; StatType_count=@($taskValidated.enums.StatType.members.PSObject.Properties).Count; HeroClass=$taskValidated.enums.HeroClass.members; EquipSlotId=$taskValidated.enums.EquipSlotId.members }
