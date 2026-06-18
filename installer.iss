; FlowZoo Studio — Inno Setup installer script.
; Build the app first (run build_windows.bat), then open this file in Inno Setup
; (https://jrsoftware.org/isinfo.php) and click Compile. Produces a single
; FlowZooStudio-Setup.exe that installs the app with Start-menu + desktop icons.

[Setup]
AppName=FlowZoo Studio
AppVersion=0.1.0
AppPublisher=Saleh Rezaee
DefaultDirName={autopf}\FlowZoo Studio
DefaultGroupName=FlowZoo Studio
OutputBaseFilename=FlowZooStudio-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern

[Files]
Source: "dist\FlowZooStudio\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\FlowZoo Studio"; Filename: "{app}\FlowZooStudio.exe"
Name: "{commondesktop}\FlowZoo Studio"; Filename: "{app}\FlowZooStudio.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\FlowZooStudio.exe"; Description: "Launch FlowZoo Studio"; Flags: nowait postinstall skipifsilent
