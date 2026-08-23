# M2 标定对局：Hellcopter vs Velvet v8.1.1 (UCI_Elo 限制档)
# 用法: .\run_m2.ps1 -elo 2200 [-rounds 200]
# 前提: arena/copter/Hellcopter.exe 与 arena/velvet/velvet-*.exe 已就位
#
# 资源纪律(GOAL.md 第0条): 并发固定 4 —— 8 个单线程引擎进程, <1GB 内存, 禁改满载
# 比赛条件: 双方均无 opening book / 无 EGTB (copter 目录已验证干净;
#           velvet 目录仅含引擎 exe; Hellcopter 的 OwnBook 默认 false)
param(
    [int]$elo = 2200,
    [int]$rounds = 200,
    [int]$concurrency = 4
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$gamesDir = Join-Path $PSScriptRoot "games"
if (-not (Test-Path $gamesDir)) { New-Item -ItemType Directory -Force $gamesDir | Out-Null }

$velvetExe = (Get-ChildItem (Join-Path $PSScriptRoot "velvet") -Filter *.exe | Select-Object -First 1).Name
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$pgn = Join-Path $PSScriptRoot "m2_velvet${elo}_$stamp.pgn"
$log = Join-Path $gamesDir "m2_velvet${elo}_progress.log"

& (Join-Path $root "cutechess-1.3.1-win64\cutechess-cli.exe") `
    -engine name=Hellcopter proto=uci cmd=Hellcopter.exe dir=..\copter `
    -engine name="Velvet_$elo" proto=uci cmd=$velvetExe dir=..\velvet `
        option=UCI_LimitStrength=true `
        "option=UCI_Elo=$elo" `
        option=SimulateThinkingTime=false `
        option=Style=Normal `
    -each tc=96+0.8 `
    -openings file=..\openings.epd format=epd order=random `
    -rounds $rounds -concurrency $concurrency -srand $(Get-Random) `
    -draw movenumber=40 movecount=8 score=20 `
    -resign movecount=4 score=600 `
    -pgnout $pgn 2>&1 | Tee-Object -FilePath $log
