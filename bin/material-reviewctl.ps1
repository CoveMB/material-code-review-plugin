$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Controller = Join-Path $Root "skills/material-code-review/scripts/reviewctl.py"
if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 $Controller @args
  exit $LASTEXITCODE
}
if (Get-Command python3 -ErrorAction SilentlyContinue) {
  & python3 $Controller @args
  exit $LASTEXITCODE
}
if (Get-Command python -ErrorAction SilentlyContinue) {
  & python $Controller @args
  exit $LASTEXITCODE
}
throw "material-reviewctl requires Python 3.10 or newer"
