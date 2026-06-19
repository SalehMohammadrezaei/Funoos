; Funoos Studio — Inno Setup installer script.
; Build the app first (run build_windows.bat), then open this file in Inno Setup
; (https://jrsoftware.org/isinfo.php) and click Compile. Produces a single
; FunoosStudio-Setup.exe that installs the app with Start-menu + desktop icons.

[Setup]
AppName=Funoos Studio
AppVersion=0.1.0
AppPublisher=Saleh Rezaee
DefaultDirName={autopf}\Funoos Studio
DefaultGroupName=Funoos Studio
OutputBaseFilename=FunoosStudio-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern

[Files]
Source: "dist\FunoosStudio\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Funoos Studio"; Filename: "{app}\FunoosStudio.exe"
Name: "{commondesktop}\Funoos Studio"; Filename: "{app}\FunoosStudio.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\FunoosStudio.exe"; Description: "Launch Funoos Studio"; Flags: nowait postinstall skipifsilent
