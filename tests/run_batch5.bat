@echo off
cd /d "E:\world\python\chess"
start /b "" "cutechess-1.3.1-win64\cutechess-cli.exe" -engine name=Baseline proto=uci dir=tmp_baseline cmd=Hellcopter.exe -engine name=Abl_Pawn proto=uci dir=tmp_abl_pawn cmd=Hellcopter.exe -each nodes=1000000 st=999999 -rounds 100 -concurrency 8 -draw movenumber=40 movecount=5 score=20 -resign movecount=3 score=500 -pgnout results\abl_pawn_batch5_20260718_bg.pgn > results\abl_pawn_batch5_20260718_bg.log 2>&1
