# Native OCR adapter. It emits observations, never authoritative game facts.
param(
    [string]$ImagePath,
    [string]$Language = 'en-US',
    [string]$NumericRegions,
    [switch]$Capabilities
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
    [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapTransform, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapBounds, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapPixelFormat, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapAlphaMode, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.ExifOrientationMode, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.ColorManagementMode, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
    [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
    [Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
    [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime] | Out-Null
    $AwaitMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
                       $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 } |
        Select-Object -First 1
    function Await-Result($Operation, $ResultType) {
        $Task = $AwaitMethod.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
        if (-not $Task.Wait(10000)) { throw 'ocr_timeout' }
        return $Task.Result
    }
    if ($Capabilities) {
        @{languages=@([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })} | ConvertTo-Json -Compress
        exit 0
    }
    $OcrLanguage = [Windows.Globalization.Language]::new($Language)
    if (-not [Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($OcrLanguage)) {
        @{error='ocr_language_unavailable'} | ConvertTo-Json -Compress
        exit 2
    }
    $Engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($OcrLanguage)
    $File = Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
    $Stream = Await-Result ($File.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $Decoder = Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($Stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        if ($NumericRegions) {
            if ($NumericRegions.Length -gt 4096) { throw 'invalid_numeric_regions' }
            $RequestText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($NumericRegions))
            [array]$Requested = $RequestText | ConvertFrom-Json
            if ($Requested.Count -lt 1 -or $Requested.Count -gt 3) { throw 'invalid_numeric_regions' }
            $NumericLanguage = [Windows.Globalization.Language]::new('en-US')
            if (-not [Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($NumericLanguage)) {
                @{error='ocr_language_unavailable'} | ConvertTo-Json -Compress
                exit 2
            }
            $NumericEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($NumericLanguage)
            $Regions = @()
            $SeenFields = @{}
            foreach ($RequestedRegion in $Requested) {
                if ($RequestedRegion.field -notin @('level','vitality','armor') -or $SeenFields.ContainsKey($RequestedRegion.field)) {
                    throw 'invalid_numeric_regions'
                }
                $SeenFields[$RequestedRegion.field] = $true
                $RequestedBounds = $RequestedRegion.bounds
                foreach ($Axis in @('x','y','width','height')) {
                    $Value = $RequestedBounds.$Axis
                    if (($Value -isnot [int] -and $Value -isnot [long]) -or $Value -lt 0 -or $Value -gt 1600) {
                        throw 'invalid_numeric_regions'
                    }
                }
                if ($RequestedBounds.width -le 0 -or $RequestedBounds.height -le 0 -or
                    $RequestedBounds.x+$RequestedBounds.width -gt $Decoder.PixelWidth -or
                    $RequestedBounds.y+$RequestedBounds.height -gt $Decoder.PixelHeight) {
                    throw 'invalid_numeric_regions'
                }
                $Transform = [Windows.Graphics.Imaging.BitmapTransform]::new()
                $CropBounds = [Activator]::CreateInstance([Windows.Graphics.Imaging.BitmapBounds])
                $CropBounds.X = [uint32]$RequestedBounds.x
                $CropBounds.Y = [uint32]$RequestedBounds.y
                $CropBounds.Width = [uint32]$RequestedBounds.width
                $CropBounds.Height = [uint32]$RequestedBounds.height
                $Transform.Bounds = $CropBounds
                $CropBitmap = Await-Result ($Decoder.GetSoftwareBitmapAsync(
                    [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
                    [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
                    $Transform,
                    [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,
                    [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage
                )) ([Windows.Graphics.Imaging.SoftwareBitmap])
                try {
                    $CropRecognition = Await-Result ($NumericEngine.RecognizeAsync($CropBitmap)) ([Windows.Media.Ocr.OcrResult])
                    $CropLines = @()
                    foreach ($Line in $CropRecognition.Lines) {
                        $Words = @()
                        foreach ($Word in $Line.Words) {
                            $Rectangle = $Word.BoundingRect
                            $Words += @{text=$Word.Text; bounds=@{
                                x=$Rectangle.X+$RequestedBounds.x; y=$Rectangle.Y+$RequestedBounds.y;
                                width=$Rectangle.Width; height=$Rectangle.Height
                            }}
                        }
                        $CropLines += @{text=$Line.Text; words=$Words}
                    }
                    $Regions += @{field=$RequestedRegion.field; bounds=$RequestedBounds;
                                  language='en-US'; text=$CropRecognition.Text; lines=$CropLines}
                } finally { $CropBitmap.Dispose() }
            }
            @{numeric_regions=$Regions} | ConvertTo-Json -Depth 10 -Compress
            exit 0
        }
        $Bitmap = Await-Result ($Decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        try {
            $Recognition = Await-Result ($Engine.RecognizeAsync($Bitmap)) ([Windows.Media.Ocr.OcrResult])
            $Lines = @()
            foreach ($Line in $Recognition.Lines) {
                $Words = @()
                foreach ($Word in $Line.Words) {
                    $Rectangle = $Word.BoundingRect
                    $Words += @{text=$Word.Text; bounds=@{x=$Rectangle.X;y=$Rectangle.Y;width=$Rectangle.Width;height=$Rectangle.Height}}
                }
                $Lines += @{text=$Line.Text; words=$Words}
            }
            $NumericReference = $null
            if ($Language -like 'zh-*' -and [Windows.Media.Ocr.OcrEngine]::IsLanguageSupported([Windows.Globalization.Language]::new('en-US'))) {
                try {
                    $NumericEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US'))
                    $NumericRecognition = Await-Result ($NumericEngine.RecognizeAsync($Bitmap)) ([Windows.Media.Ocr.OcrResult])
                    $NumericLines = @()
                    foreach ($Line in $NumericRecognition.Lines) {
                        $Words = @()
                        foreach ($Word in $Line.Words) {
                            $Rectangle = $Word.BoundingRect
                            $Words += @{text=$Word.Text; bounds=@{x=$Rectangle.X;y=$Rectangle.Y;width=$Rectangle.Width;height=$Rectangle.Height}}
                        }
                        $NumericLines += @{text=$Line.Text; words=$Words}
                    }
                    $NumericReference = @{language='en-US'; text=$NumericRecognition.Text; lines=$NumericLines}
                } catch { $NumericReference = $null }
            }
            @{text=$Recognition.Text; language=$Engine.RecognizerLanguage.LanguageTag; lines=$Lines; numeric_reference=$NumericReference} |
                ConvertTo-Json -Depth 10 -Compress
        } finally { $Bitmap.Dispose() }
    } finally { $Stream.Dispose() }
} catch {
    @{error='ocr_failed'} | ConvertTo-Json -Compress
    exit 1
}
