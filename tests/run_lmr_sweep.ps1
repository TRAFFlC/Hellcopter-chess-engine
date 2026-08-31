$variants = @(
    @{name="b0.5_d2.0"},
    @{name="b0.5_d2.5"},
    @{name="b0.5_d3.0"},
    @{name="b0.75_d2.0"},
    @{name="b0.75_d3.0"},
    @{name="b1.0_d2.0"},
    @{name="b1.0_d2.5"},
    @{name="b1.0_d3.0"}
)

$resultsDir = "results"
$cutechess = "cutechess-1.3.1-win64\cutechess-cli.exe"
$timestamp = Get-Date -Format "yyyyMMdd_HHmm"

foreach ($v in $variants) {
    $name = $v.name
    $pgn = "$resultsDir\lmr_sweep_${name}_${timestamp}.pgn"
    $log = "$resultsDir\lmr_sweep_${name}_${timestamp}.log"

    Write-Host "`n=== Running: $name vs baseline (0.75/2.5) ==="

    & $cutechess `
        -engine name=$name proto=uci cmd="tmp_lmr_sweep/$name/Hellcopter.exe" dir="tmp_lmr_sweep/$name" `
        -engine name=baseline proto=uci cmd="tmp_lmr_sweep/baseline/Hellcopter.exe" dir="tmp_lmr_sweep/baseline" `
        -each nodes=1000000 st=999999 `
        -rounds 200 -concurrency 8 `
        -draw movenumber=40 movecount=5 score=20 `
        -resign movecount=3 score=500 `
        -sprt elo0=-2 elo1=5 alpha=0.05 beta=0.05 `
        -pgnout $pgn 2>&1 | Tee-Object -FilePath $log

    Write-Host "`n=== Finished: $name ==="
}
