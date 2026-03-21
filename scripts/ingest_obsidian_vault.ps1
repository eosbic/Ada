param(
    [Parameter(Mandatory = $true)]
    [string]$EmpresaId,

    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$VaultPath = ".\obsidian-vault",
    [string]$Instruction = "Ingesta de nota Markdown desde Obsidian para base de conocimiento.",
    [switch]$IncludeTemplates
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

if (-not (Test-Path $VaultPath)) {
    throw "No existe la carpeta del vault: $VaultPath"
}

$resolvedVault = (Resolve-Path $VaultPath).Path
$uploadUrl = "$ApiBaseUrl/files/upload"

Write-Host "Vault:" $resolvedVault
Write-Host "Endpoint:" $uploadUrl
Write-Host "EmpresaId:" $EmpresaId

$files = Get-ChildItem -Path $resolvedVault -Recurse -File -Include *.md, *.markdown

if (-not $IncludeTemplates) {
    $files = $files | Where-Object { $_.FullName -notmatch "\\Templates\\" }
}

if (-not $files -or $files.Count -eq 0) {
    Write-Host "No se encontraron archivos Markdown para ingerir."
    exit 0
}

$ok = 0
$failed = 0

foreach ($f in $files) {
    try {
        $client = New-Object System.Net.Http.HttpClient
        $content = New-Object System.Net.Http.MultipartFormDataContent

        $empresaContent = New-Object System.Net.Http.StringContent($EmpresaId, [System.Text.Encoding]::UTF8)
        $instructionContent = New-Object System.Net.Http.StringContent($Instruction, [System.Text.Encoding]::UTF8)
        $industryContent = New-Object System.Net.Http.StringContent("generic", [System.Text.Encoding]::UTF8)
        $content.Add($empresaContent, "empresa_id")
        $content.Add($instructionContent, "instruction")
        $content.Add($industryContent, "industry_type")

        [byte[]]$bytes = [System.IO.File]::ReadAllBytes($f.FullName)
        $fileContent = New-Object System.Net.Http.ByteArrayContent -ArgumentList (, $bytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("text/markdown")
        $content.Add($fileContent, "file", $f.Name)

        $response = $client.PostAsync($uploadUrl, $content).GetAwaiter().GetResult()
        $raw = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $res = $null
        if ($raw) {
            try {
                $res = $raw | ConvertFrom-Json
            } catch {
                $res = $null
            }
        }

        if (-not $response.IsSuccessStatusCode) {
            $failed++
            Write-Host "[ERROR] $($f.Name): HTTP $([int]$response.StatusCode) $raw"
        } elseif ($res -and $res.error) {
            $failed++
            Write-Host "[ERROR] $($f.Name): $($res.error)"
        } else {
            $ok++
            if ($res -and $res.file_type) {
                Write-Host "[OK] $($f.Name) -> $($res.file_type)"
            } else {
                Write-Host "[OK] $($f.Name)"
            }
        }

        $fileContent.Dispose()
        $content.Dispose()
        $client.Dispose()
    } catch {
        $failed++
        Write-Host "[ERROR] $($f.Name): $($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "Resumen:"
Write-Host "- Exitosos:" $ok
Write-Host "- Fallidos:" $failed
