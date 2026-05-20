param(
    [int]$Port = 8001,

    [string]$HostName = "127.0.0.1",

    [int]$ReadyTimeoutSeconds = 15,

    [string]$NgrokPath = "",

    [string]$Region = "eu",

    [switch]$KeepDjangoOnExit
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DjangoServerScript = Join-Path $PSScriptRoot "django_server.ps1"

function Merge-CsvEnvironmentValue {
    param(
        [string]$CurrentValue,
        [string[]]$RequiredValues
    )

    $values = New-Object System.Collections.Generic.List[string]

    foreach ($item in ($CurrentValue -split ",")) {
        $value = $item.Trim()
        if ($value -and -not $values.Contains($value)) {
            $values.Add($value)
        }
    }

    foreach ($item in $RequiredValues) {
        $value = $item.Trim()
        if ($value -and -not $values.Contains($value)) {
            $values.Add($value)
        }
    }

    return ($values -join ",")
}

function Resolve-NgrokPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        if (Test-Path -LiteralPath $RequestedPath) {
            return (Resolve-Path -LiteralPath $RequestedPath).Path
        }
        throw "ngrok not found at: $RequestedPath"
    }

    $command = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @()
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ngrok.exe"
    }
    $candidates += "C:\ngrok\ngrok.exe"

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "ngrok is not installed or is not visible in PATH."
}

if (-not (Test-Path -LiteralPath $DjangoServerScript)) {
    throw "Django server helper not found: $DjangoServerScript"
}

$ngrok = Resolve-NgrokPath -RequestedPath $NgrokPath

$env:DJANGO_ALLOWED_HOSTS = Merge-CsvEnvironmentValue `
    -CurrentValue $env:DJANGO_ALLOWED_HOSTS `
    -RequiredValues @(
        "localhost",
        "127.0.0.1",
        ".ngrok-free.app",
        ".ngrok-free.dev",
        ".ngrok.app",
        ".ngrok.io"
    )

$env:DJANGO_CSRF_TRUSTED_ORIGINS = Merge-CsvEnvironmentValue `
    -CurrentValue $env:DJANGO_CSRF_TRUSTED_ORIGINS `
    -RequiredValues @(
        "https://*.ngrok-free.app",
        "https://*.ngrok-free.dev",
        "https://*.ngrok.app",
        "https://*.ngrok.io"
    )

$env:DJANGO_TRUST_X_FORWARDED_PROTO = "true"

Write-Output "Starting Kabinet.pro locally on http://$HostName`:$Port ..."
& $DjangoServerScript -Action restart -Port $Port -HostName $HostName -ReadyTimeoutSeconds $ReadyTimeoutSeconds

Write-Output ""
Write-Output "Starting ngrok. Copy the https://*.ngrok-free.* forwarding link from the output below."
Write-Output "ngrok options: region=$Region."
Write-Output "Press Ctrl+C to stop the public tunnel."
Write-Output ""

try {
    & $ngrok http --region $Region "http://$HostName`:$Port"
} finally {
    if ($KeepDjangoOnExit) {
        Write-Output "ngrok stopped. Django is still running on http://$HostName`:$Port."
    } else {
        Write-Output "Stopping local Django server..."
        & $DjangoServerScript -Action stop -Port $Port -HostName $HostName
    }
}
