# SEE fix A/B test — baseline (SEE off) vs experiment (SEE on, fixed thresholds)
# 8 parallel instances × 50 rounds each @ 96+0.8

$baseDir = "E:\world\python\chess"
$resultsDir = Join-Path $baseDir "results"
$cutechess = Join-Path $baseDir "cutechess-1.3.1-win64\cutechess-cli.exe"
$python = "python"
$configA = Join-Path $baseDir "configs\see_off.json"
$configB = Join-Path $baseDir "configs\see_on.json"

Write-Host "=== SEE A/B Test ==="
Write-Host "Baseline (A):  SEE pruning OFF"
Write-Host "Experiment (B): SEE pruning ON (fix applied)"
Write-Host "TC: 96+0.8, Rounds: 400 (8 x 50)"
Write-Host "Concurrency: 1 per instance"
Write-Host ""

# Create adapters
$adapterInfo = python -c @"
import sys, os, json, tempfile
sys.path.insert(0, '$baseDir')
from match_utils import create_temp_uci_adapter_with_env

info = {'A': [], 'B': []}
for i in range(8):
    path_a, dir_a = create_temp_uci_adapter_with_env(r'$baseDir', r'$configA', f'see_off_{i}')
    path_b, dir_b = create_temp_uci_adapter_with_env(r'$baseDir', r'$configB', f'see_on_{i}')
    info['A'].append(path_a)
    info['B'].append(path_b)
print(json.dumps(info))
"@

# Parse adapter info
$info = $adapterInfo | ConvertFrom-Json
$adaptersA = $info.A
$adaptersB = $info.B

Write-Host "Created $($adaptersA.Count) + $($adaptersB.Count) adapters"

$jobs = @()
for ($i = 0; $i -lt 8; $i++) {
    # Clean previous PGN if exists
    $pgnFile = Join-Path $resultsDir "see_test_$('{0:D2}' -f ($i+1)).pgn"
    if (Test-Path $pgnFile) { Remove-Item $pgnFile -Force }
    
    $adapterA = $adaptersA[$i]
    $adapterB = $adaptersB[$i]
    $adapterADir = Split-Path $adapterA -Parent
    $adapterBDir = Split-Path $adapterB -Parent

    $job = Start-Job -ScriptBlock {
        param($ce, $py, $aa, $ab, $adir, $bdir, $pgn, $id)
        & $ce `
            -engine name=Baseline proto=uci cmd=$py arg=$aa dir=$adir `
            -engine name=Experiment proto=uci cmd=$py arg=$ab dir=$bdir `
            -each tc=96+0.8 `
            -rounds 50 -concurrency 1 `
            -draw movenumber=40 movecount=5 score=20 `
            -resign movecount=3 score=500 `
            -pgnout $pgn 2>&1
    } -ArgumentList $cutechess, $python, $adapterA, $adapterB, $adapterADir, $adapterBDir, $pgnFile, $i
    $jobs += $job
    Write-Host "Started instance $($i+1) (job id $($job.Id))"
    Start-Sleep -Milliseconds 500
}

Write-Host "All 8 instances started. Waiting for completion..."
$jobs | Wait-Job | Out-Null

Write-Host "=== All instances completed ==="
foreach ($job in $jobs) {
    $output = Receive-Job $job
    Write-Host "Job $($job.Id): $output"
}

# Aggregate
$bWins=0; $eWins=0; $draws=0; $total=0
for ($i = 0; $i -lt 8; $i++) {
    $pgn = Join-Path $resultsDir "see_test_$('{0:D2}' -f ($i+1)).pgn"
    if (Test-Path $pgn) {
        $c = Get-Content $pgn -Raw
        $r = [regex]::Matches($c, '\[Result "([^"]+)"\]')
        foreach ($x in $r) {
            $total++
            switch ($x.Groups[1].Value) {
                "1-0" { $bWins++ }
                "0-1" { $eWins++ }
                "1/2-1/2" { $draws++ }
            }
        }
    }
}

Write-Host "`n=== Aggregated Results ==="
Write-Host "Total: $total  Baseline(SEE off): $bWins  Experiment(SEE on): $eWins  Draws: $draws"
if ($total -gt 0) {
    $bs = $bWins + $draws/2
    $es = $eWins + $draws/2
    $bp = [Math]::Round($bs/$total*100,1)
    $ep = [Math]::Round($es/$total*100,1)
    Write-Host "Baseline: $bs/$total ($bp%)  Experiment: $es/$total ($ep%)"
    $elo = [Math]::Round(400*[Math]::Log10($es/($bs)),1)
    Write-Host "Elo diff (Experiment vs Baseline): $elo"
}

# Cleanup
foreach ($a in ($adaptersA + $adaptersB)) {
    $d = Split-Path $a -Parent
    if (Test-Path $d) { Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue }
}
