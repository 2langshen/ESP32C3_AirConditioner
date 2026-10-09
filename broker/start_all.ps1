# Start the LAN MQTT broker + Siri HTTP bridge (run this on the PC).
$b = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process -FilePath "python" -ArgumentList "$b\minibroker.py", "0.0.0.0", "1883" `
    -WorkingDirectory $b -WindowStyle Hidden `
    -RedirectStandardOutput "$b\minibroker.log" -RedirectStandardError "$b\minibroker.err"
Start-Sleep -Seconds 1
Start-Process -FilePath "python" -ArgumentList "$b\siri_http.py" `
    -WorkingDirectory $b -WindowStyle Hidden `
    -RedirectStandardOutput "$b\siri.log" -RedirectStandardError "$b\siri.err"
Write-Output "broker :1883 + siri-bridge :8080 started."
