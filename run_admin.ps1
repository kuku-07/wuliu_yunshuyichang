# 管理后台启动脚本（PowerShell）
# 本机 Python 的 site-packages 位于 D:\Lib\site-packages，但未自动加入 sys.path，
# 因此这里显式设置 PYTHONPATH；换机器时删除该行即可。
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$paths = @($root)
if (Test-Path "D:\Lib\site-packages") {
    $paths = @("D:\Lib\site-packages") + $paths
}
$env:PYTHONPATH = ($paths -join ";")

python -m uvicorn admin_app.main:app --host 127.0.0.1 --port 8088
