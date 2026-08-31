$baseDir = "E:\world\python\chess"
$cutechess = Join-Path $baseDir "cutechess-1.3.1-win64\cutechess-cli.exe"
$resultsDir = Join-Path $baseDir "results"
$oldEngine = Join-Path $baseDir "Hellcopter_old.exe"
$newEngine = Join-Path $baseDir "Hellcopter_new.exe"

if (-not (Test-Path $resultsDir)) { New-Item -ItemType Directory -Path $resultsDir -Force }

$instances = 8
$roundsPerInstance = 50

Write-Host "=== Time Management A/B Test ==="
Write-Host "Baseline:  Hellcopter_old.exe (commit 7e0a008)"
Write-Host "Experiment: Hellcopter_new.exe (current HEAD)"
Write-Host "TC: 10+0.2, Rounds: $($instances * $roundsPerInstance) ($instances x $roundsPerInstance)"
Write-Host "Concurrency: 1 per instance (total $instances engine processes)"
Write-Host ""

$jobs = @()
for ($i = 1; $i -le $instances; $i++) {
    $pgn = Join-Path $resultsDir "tm_vs_baseline_$("{0:D2}" -f $i).pgn"
    $job = Start-Job -ScriptBlock {
        param($exe, $old, $new, $pgn, $rounds)
        & $exe `
            -engine name=Baseline proto=uci cmd=$old `
            -engine name=Experiment proto=uci cmd=$new `
            -each tc=10+0.2 -rounds $rounds -concurrency 1 `
            -draw movenumber=40 movecount=5 score=20 `
            -resign movecount=3 score=500 `
            -pgnout $pgn
    } -ArgumentList $cutechess, $oldEngine, $newEngine, $pgn, $roundsPerInstance
    $jobs += $job
    Write-Host "Started instance $i (job id $($job.Id))"
}

Write-Host "`nAll $instances instances started (concurrency=1 each)."
Write-Host "Run 'Get-Job | Where-Object { `$_.State -eq 'Running' }' to check progress."

$jobs | Wait-Job | Out-Null

Write-Host "`n=== All instances completed ==="
foreach ($job in $jobs) {
    $output = Receive-Job -Job $job
    if ($output) { Write-Host "Job $($job.Id): $output" }
}
