; Funoos — Inno Setup installer script.
; Build the app first (run build_windows.bat), then open this file in Inno Setup
; (https://jrsoftware.org/isinfo.php) and click Compile. Produces a single
; Funoos-Setup.exe that installs the app with Start-menu + desktop icons —
; the end user needs no Python, no compiler, nothing else.

[Setup]
AppName=Funoos
AppVersion=1.0.0
AppPublisher=Saleh Mohammadrezaei
DefaultDirName={autopf}\Funoos
DefaultGroupName=Funoos
OutputBaseFilename=Funoos-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern

[Files]
Source: "dist\Funoos\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Funoos"; Filename: "{app}\Funoos.exe"
Name: "{commondesktop}\Funoos"; Filename: "{app}\Funoos.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\Funoos.exe"; Description: "Launch Funoos"; Flags: nowait postinstall skipifsilent
