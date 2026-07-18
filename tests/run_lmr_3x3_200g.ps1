$Python = "python"
$Script = "E:\world\python\chess\run_match.py"
$Baseline = "configs\v1.9.5.json"
$Date = Get-Date -Format "yyyyMMdd_HHmm"
$Rounds = 100  # 100 rounds = 200 games per config

# 3x3 grid: all 8 variants + 1 baseline self-play
$All = @(
    # base=0.50 row
    @("lmr_b0.5_d1.5",  "configs\lmr_b0.5_d1.5.json"),
    @("lmr_b0.5_d2",    "configs\lmr_b0.5_d2.json"),
    @("lmr_b0.5_d2.5",  "configs\lmr_b0.5_d2.5.json"),
    # base=0.75 row (skip baseline)
    @("lmr_b0.75_d1.5", "configs\lmr_b0.75_d1.5.json"),
    @("lmr_b0.75_d2.5", "configs\lmr_b0.75_d2.5.json"),
    # base=1.00 row
    @("lmr_b1_d1.5",    "configs\lmr_b1_d1.5.json"),
    @("lmr_b1_d2",      "configs\lmr_b1_d2.json"),
    @("lmr_b1_d2.5",    "configs\lmr_b1_d2.5.json"),
    # baseline self-play control (no SPRT)
    @("baseline_self",  "configs\v1.9.5.json")
)

Write-Host "=== LMR 3x3 Grid: $($All.Count) configs, $($Rounds*2) games each ==="
Write-Host "Start: $(Get-Date -Format 'HH:mm:ss')"
Write-Host ""

foreach ($t in $All) {
    $label = $t[0]
    $cfg = $t[1]
    $log = "results\lmr_3x3_${label}_${Date}.log"
    $pgn = "results\lmr_3x3_${label}_${Date}.pgn"
    
    if ($label -eq "baseline_self") {
        # Baseline self-play: A=v1.9.5, B=v1.9.5, no SPRT
        $args = "$Script --mode self --config-a $Baseline --config-b $Baseline --rounds $Rounds --tc 10+0.2 --pgnout $pgn"
    } else {
        # Variant vs baseline: A=variant, B=baseline, SPRT -2/5
        $args = "$Script --mode self --config-a $cfg --config-b $Baseline --rounds $Rounds --tc 10+0.2 --sprt=-2,5,0.05,0.10 --pgnout $pgn"
    }
    
    Write-Host "  $label -> $log"
    Start-Process -FilePath $Python -WindowStyle Hidden -ArgumentList $args -RedirectStandardOutput $log
}

Write-Host ""
Write-Host "All launched at $(Get-Date -Format 'HH:mm:ss')"
Write-Host "Check progress: tail results\lmr_3x3_*.log"