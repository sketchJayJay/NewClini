Set WshShell = CreateObject("WScript.Shell")
bat = Chr(34) & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\start_windows.bat" & Chr(34)
WshShell.Run bat, 0, False
