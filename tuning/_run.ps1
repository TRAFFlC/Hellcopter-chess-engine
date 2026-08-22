$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUNBUFFERED='1'
$log = Join-Path $PSScriptRoot "texel_run.log"
python $PSScriptRoot/run_texel.py *>&1 | Out-File -FilePath $log -Encoding utf8
