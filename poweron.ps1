gsudo cache on   # 最多提示一次

$launchScript = @'
Start-Process -FilePath 'nvidia-smi' -ArgumentList '-lgc','200,210' -Wait
# 1500
# Start-Process 'S:\apps\maa\March7thAssistant_full\March7th Launcher.exe'  -WorkingDirectory 'S:\apps\maa\March7thAssistant_full'
# Start-Process 'S:\apps\maa\ok-nte\ok-nte.exe'        -WorkingDirectory 'S:\apps\maa\ok-nte' -WindowStyle Minimized
# Start-Process 'C:\Program Files\yysls\Win32\deploy\launcher.exe'  -WorkingDirectory 'C:\Program Files\yysls\Win32\deploy'


# Start-Process 'S:\apps\maa\MaaLYSK-win-x86_64-v0.4.3-beta1\MaaLYSK.exe' -WorkingDirectory 'S:\apps\maa\MaaLYSK-win-x86_64-v0.4.3-beta1' -WindowStyle Minimized
# Start-Process 'S:\apps\maa\m9a-mxu\M9A.exe'     -ArgumentList '--autostart'     -WorkingDirectory 'S:\apps\maa\m9a-mxu' 
# Start-Process 'S:\apps\maa\BetterGI\BetterGI.exe'    -WorkingDirectory 'S:\apps\maa\BetterGI'
# Start-Process 'S:\apps\maa\ok-ww\ok-ww.exe'         -WorkingDirectory 'S:\apps\maa\ok-ww' -WindowStyle Minimized
'@

$bytes   = [System.Text.Encoding]::Unicode.GetBytes($launchScript)
$encoded = [Convert]::ToBase64String($bytes)
gsudo powershell -NoProfile -EncodedCommand $encoded   # cache 命中，不再提示

# ===================================================================
# CapsWriter-Offline 语音输入：S:\asr 的 Qwen3-ASR-1.7B（CrispASR q8_0 GGUF，常驻 HTTP 服务），解码走 RTX 4060 CUDA
# 服务端先拉起 crispasr.exe --server 并加载模型（约 5.5 秒，含 1.5 秒首推理预热），客户端自带断线重连，紧跟着起即可
# ===================================================================
Start-Process 'C:\Users\Public\app\CapsWriter-Offline\start_server.exe' -WorkingDirectory 'C:\Users\Public\app\CapsWriter-Offline' -WindowStyle Minimized
Start-Process 'C:\Users\Public\app\CapsWriter-Offline\start_client.exe' -WorkingDirectory 'C:\Users\Public\app\CapsWriter-Offline' -WindowStyle Minimized
