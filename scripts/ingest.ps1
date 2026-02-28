# Merlin Ingest - organiza + sha256 + manifest.csv
# Ejecutar desde storage/incoming o pasar -SourceDir

param(
  [string]$SourceDir = ""
)

$categorias = @{
  "DOCUMENTOS" = @("PDF","DOC","DOCX","TXT","XLS","XLSX","PPT","PPTX","CSV","MD")
  "OTROS"      = @()
}

$sizeLimit = 500MB
$scriptName = $MyInvocation.MyCommand.Name

if ([string]::IsNullOrWhiteSpace($SourceDir)) {
  $SourceDir = (Get-Location).Path
}

$processedRoot = Join-Path (Resolve-Path "$SourceDir\..\processed").Path "DOCS"
$manifestPath  = Join-Path (Resolve-Path "$SourceDir\..\processed").Path "manifest.csv"

if (!(Test-Path $processedRoot)) { New-Item -ItemType Directory -Path $processedRoot -Force | Out-Null }

if (!(Test-Path $manifestPath)) {
  "original_filename,stored_path,sha256,size_bytes,ext,category,year,last_write_time" | Out-File -Encoding UTF8 $manifestPath
}

Write-Host "Iniciando ingesta Merlin desde: $SourceDir" -ForegroundColor Cyan
Write-Host "Destino procesados: $processedRoot" -ForegroundColor Cyan

$files = Get-ChildItem -Path $SourceDir -File | Where-Object { $_.Name -ne $scriptName }

foreach ($file in $files) {
  $ext = $file.Extension.TrimStart('.').ToUpper()
  if ([string]::IsNullOrWhiteSpace($ext)) { $ext = "SIN_EXTENSION" }

  $year = $file.LastWriteTime.Year.ToString()

  # categoría
  $categoriaEncontrada = "OTROS"
  foreach ($cat in $categorias.Keys) {
    if ($categorias[$cat] -contains $ext) {
      $categoriaEncontrada = $cat
      break
    }
  }

  if ($file.Length -gt $sizeLimit) {
    $categoriaEncontrada = "!00_REVISAR_PESADOS"
  }

  # estructura: DOCS/<CATEGORIA>/<EXT>/<AÑO>/
  $finalPath = Join-Path $processedRoot $categoriaEncontrada
  $finalPath = Join-Path $finalPath $ext
  $finalPath = Join-Path $finalPath $year

  if (!(Test-Path $finalPath)) { New-Item -ItemType Directory -Path $finalPath -Force | Out-Null }

  # hash para dedupe
  $sha256 = (Get-FileHash -Algorithm SHA256 -Path $file.FullName).Hash

  $destinationFile = Join-Path $finalPath $file.Name
  if (Test-Path $destinationFile) {
    $uniqueId = [guid]::NewGuid().ToString().Substring(0,5)
    $newName = "$($file.BaseName)_$uniqueId.$($file.Extension.TrimStart('.'))"
    $destinationFile = Join-Path $finalPath $newName
  }

  Move-Item -Path $file.FullName -Destination $destinationFile

  $line = """$($file.Name)"",""$destinationFile"",""$sha256"",$($file.Length),$ext,$categoriaEncontrada,$year,""$($file.LastWriteTime.ToString("o"))"""
  Add-Content -Encoding UTF8 -Path $manifestPath -Value $line
}

Write-Host "OK. Manifest generado en: $manifestPath" -ForegroundColor Green