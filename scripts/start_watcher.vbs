Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw.exe """ & Replace(WScript.ScriptFullName, "start_watcher.vbs", "client_quota_watcher.py") & """", 0, False
