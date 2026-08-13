$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item -LiteralPath (Join-Path $root 'baseline/controllers/patchright_controller.py') -Destination (Join-Path (Split-Path $root -Parent | Split-Path -Parent) 'controllers/patchright_controller.py') -Force
Copy-Item -LiteralPath (Join-Path $root 'baseline/tests/test_signup_flow.py') -Destination (Join-Path (Split-Path $root -Parent | Split-Path -Parent) 'tests/test_signup_flow.py') -Force
