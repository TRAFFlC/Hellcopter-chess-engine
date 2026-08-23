# M1 标定对局：Hellcopter vs Monarch 2005 v1.7 (约 2000 Elo)
# 用法: .\run_m1.ps1 [-rounds 240]
# 前提: arena/copter/{Hellcopter.exe, engine_params.json} 与 arena/monarch/*.exe 已就位
#       engine_params.json = resolved(v1.9.5) + Threads=1 (tests/make_arena_config.py 生成)
#
# 资源纪律(GOAL.md 第0条): 并发固定 4 —— 8 个单线程引擎进程, <1GB 内存, 禁改满载
# 比赛条件: 双方均无 opening book / 无 EGTB (copter 目录已验证干净;
#           monarch 目录仅含引擎 exe; Hellcopter 的 OwnBook 默认 false)
param(
    [int]$rounds = 240,
    [int]$concurrency = 4
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$root = Split-Path $PSScriptRoot -Parent
$gamesDir = Join-Path $PSScriptRoot "games"
if (-not (Test-Path $gamesDir)) { New-Item -ItemType Directory -Force $gamesDir | Out-Null }

$monarchExe = (Get-ChildItem (Join-Path $PSScriptRoot "monarch") -Filter *.exe | Select-Object -First 1).Name
$copterDir = Join-Path $PSScriptRoot "copter"
$monarchDir = Join-Path $PSScriptRoot "monarch"
$epd = Join-Path $PSScriptRoot "openings.epd"
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$pgn = Join-Path $PSScriptRoot "m1_monarch_$stamp.pgn"
$log = Join-Path $gamesDir "m1_monarch_${stamp}_progress.log"

$ErrorActionPreference = "Continue"
& (Join-Path $root "cutechess-1.3.1-win64\cutechess-cli.exe") `
    -engine name=Hellcopter proto=uci cmd=Hellcopter.exe "dir=$copterDir" option.Threads=1 `
    -engine name=Monarch2005 proto=uci cmd=$monarchExe "dir=$monarchDir" `
    -each tc=96+0.8 `
    -openings file="$epd" format=epd order=random `
    -rounds $rounds -concurrency $concurrency -srand $(Get-Random) `
    -draw movenumber=40 movecount=8 score=20 `
    -resign movecount=4 score=600 `
    -pgnout $pgn 2>&1 | Tee-Object -FilePath $log
