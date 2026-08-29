' Hidden launcher for Task Scheduler
Set sh = CreateObject("Wscript.Shell")
Dim root
root = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
' Prefer py launcher
Dim rc
rc = sh.Run("cmd /c py -3 print_agent.py >> agent.log 2>&1", 0, False)
If rc = 0 Then
  ' started
Else
  sh.Run "cmd /c python print_agent.py >> agent.log 2>&1", 0, False
End If
