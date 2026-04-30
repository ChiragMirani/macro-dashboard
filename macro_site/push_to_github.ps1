# Re-render the dashboard locally, sync everything into the public repo, push.
# Run any time you've changed templates/CSS/scripts/JSONs and want it live now.
#
#   powershell -ExecutionPolicy Bypass -File macro_site\push_to_github.ps1
#   powershell -ExecutionPolicy Bypass -File macro_site\push_to_github.ps1 -Message "fix mobile layout"

param(
    [string]$Message = ""
)

$ErrorActionPreference = 'Stop'

$Src = 'C:\Users\chira\PycharmProjects\BloombergFlyProject'
$Dst = 'C:\Users\chira\PycharmProjects\macro-dashboard'

if (-not $Message) {
    $Message = "Update dashboard $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

function Step([string]$Label) {
    Write-Host ''
    Write-Host "=== $Label ===" -ForegroundColor Cyan
}

function Run([string]$Cmd) {
    Write-Host "+ $Cmd" -ForegroundColor DarkGray
    iex $Cmd
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Cmd" }
}

# ---- 1. Refresh Kalshi + re-render so docs/ has the freshest output ----
Step "1/3: refresh Kalshi consensus and re-render dashboard"
Set-Location $Src
Run "python macro_site\build_kalshi_consensus.py"
Run "python macro_site\refresh_dashboard.py"

# ---- 2. Sync everything that lives in the public repo ----
Step "2/3: sync to public repo"
$pairs = @(
    @{ From = "$Src\docs\*";                                              To = "$Dst\docs\";                          Recurse = $true  },
    @{ From = "$Src\macro_site\refresh_dashboard.py";                     To = "$Dst\macro_site\";                    Recurse = $false },
    @{ From = "$Src\macro_site\build_kalshi_consensus.py";                To = "$Dst\macro_site\";                    Recurse = $false },
    @{ From = "$Src\macro_site\track_record.py";                           To = "$Dst\macro_site\";                    Recurse = $false },
    @{ From = "$Src\macro_site\track_record.db";                           To = "$Dst\macro_site\";                    Recurse = $false },
    @{ From = "$Src\macro_site\latest_actuals_cache.json";                To = "$Dst\macro_site\";                    Recurse = $false },
    @{ From = "$Src\macro_site\templates\index.html";                     To = "$Dst\macro_site\templates\";          Recurse = $false },
    @{ From = "$Src\macro_site\static\styles.css";                        To = "$Dst\macro_site\static\";             Recurse = $false },
    @{ From = "$Src\macro_forecasting\output\*.json";                     To = "$Dst\macro_forecasting\output\";      Recurse = $false },
    @{ From = "$Src\cpi_pce_bridge_v2.json";                              To = "$Dst\";                               Recurse = $false },
    @{ From = "$Src\report_table.csv";                                    To = "$Dst\";                               Recurse = $false },
    @{ From = "$Src\adp_run.log";                                         To = "$Dst\";                               Recurse = $false },
    @{ From = "$Src\.github\workflows\macro_dashboard_daily.yml";         To = "$Dst\.github\workflows\";             Recurse = $false }
)
foreach ($p in $pairs) {
    if ($p.Recurse) { Copy-Item -Path $p.From -Destination $p.To -Recurse -Force }
    else            { Copy-Item -Path $p.From -Destination $p.To           -Force }
}

# ---- 3. Commit + push ----
Step "3/3: commit and push"
Set-Location $Dst
Run 'git add .'
$prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& cmd /c 'git diff --cached --quiet'
$hasChanges = ($LASTEXITCODE -ne 0)
$ErrorActionPreference = $prev

if ($hasChanges) {
    Run "git commit -m `"$Message`""
    Run 'git push'
    Write-Host ''
    Write-Host "PUSHED: $Message" -ForegroundColor Green
    Write-Host 'Live in ~30s: https://chiragmirani.github.io/macro-dashboard/'
} else {
    Write-Host ''
    Write-Host 'No changes to commit — nothing to push.' -ForegroundColor Yellow
}
