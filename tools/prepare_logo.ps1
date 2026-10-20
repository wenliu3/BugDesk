# Regenerate the small web logo and multi-size Windows/browser icon from the
# selected master PNG. Uses Windows .NET only; not an application dependency.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$projectRoot = Split-Path -Parent $PSScriptRoot
$masterPath = Join-Path $projectRoot 'assets\bugdesk-logo.png'
$master = [System.Drawing.Image]::FromFile($masterPath)

function Convert-LogoPng([int]$Side) {
    $bitmap = [System.Drawing.Bitmap]::new($Side, $Side, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $stream = [System.IO.MemoryStream]::new()
    try {
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.DrawImage($master, 0, 0, $Side, $Side)
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return ,$stream.ToArray()
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
        $stream.Dispose()
    }
}

try {
    [System.IO.File]::WriteAllBytes((Join-Path $projectRoot 'web\bugdesk-logo.png'), (Convert-LogoPng 128))
    $frames = @(foreach ($side in @(16, 24, 32, 48, 64, 128, 256)) {
        @{ Side = $side; Bytes = (Convert-LogoPng $side) }
    })
    $iconStream = [System.IO.MemoryStream]::new()
    $writer = [System.IO.BinaryWriter]::new($iconStream)
    try {
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]$frames.Count)
        $offset = 6 + 16 * $frames.Count
        foreach ($frame in $frames) {
            $dimension = if ($frame.Side -eq 256) { 0 } else { $frame.Side }
            $writer.Write([byte]$dimension)
            $writer.Write([byte]$dimension)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([uint16]1)
            $writer.Write([uint16]32)
            $writer.Write([uint32]$frame.Bytes.Length)
            $writer.Write([uint32]$offset)
            $offset += $frame.Bytes.Length
        }
        foreach ($frame in $frames) { $writer.Write([byte[]]$frame.Bytes) }
        $writer.Flush()
        $iconBytes = $iconStream.ToArray()
        [System.IO.File]::WriteAllBytes((Join-Path $projectRoot 'assets\bugdesk.ico'), $iconBytes)
        [System.IO.File]::WriteAllBytes((Join-Path $projectRoot 'web\favicon.ico'), $iconBytes)
    } finally {
        $writer.Dispose()
        $iconStream.Dispose()
    }
} finally {
    $master.Dispose()
}
Write-Output 'Prepared the 128px web logo and 7-size Windows/browser icons.'
