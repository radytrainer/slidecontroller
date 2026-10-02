; AirSlide installer (Inno Setup 6).
;
; Built by build.ps1 from the program folder dist\AirSlide\ into
; dist\AirSlide-Setup-<version>.exe:
;
;   powershell -ExecutionPolicy Bypass -File build.ps1
;
; The installer asks whether to install for everyone (Program Files, needs
; administrator rights) or only for the current user (no administrator rights,
; e.g. on school computers). It adds a Start menu shortcut, an optional desktop
; shortcut, and an entry in Settings > Apps to uninstall. Settings and logs in
; %APPDATA% / %LOCALAPPDATA% are kept when AirSlide is uninstalled or updated.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; The same AppId for every version: a new installer updates the installed AirSlide.
AppId={{BDC6D471-D418-4B7F-9C63-C61EA1C109A5}
AppName=AirSlide
AppVersion={#AppVersion}
AppVerName=AirSlide {#AppVersion}
AppPublisher=AirSlide
AppComments=Present Without Touching - control PowerPoint, PDF and photo slideshows with hand gestures.
VersionInfoVersion={#AppVersion}
VersionInfoDescription=AirSlide Setup
DefaultDirName={autopf}\AirSlide
DefaultGroupName=AirSlide
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=AirSlide-Setup-{#AppVersion}
SetupIconFile=..\assets\airslide.ico
UninstallDisplayIcon={app}\AirSlide.exe
UninstallDisplayName=AirSlide
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Close a running AirSlide before updating it.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; An update replaces the program files completely (no files left from an older version).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\AirSlide\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AirSlide"; Filename: "{app}\AirSlide.exe"; Comment: "Present Without Touching"
Name: "{autodesktop}\AirSlide"; Filename: "{app}\AirSlide.exe"; Tasks: desktopicon; Comment: "Present Without Touching"

[Run]
Filename: "{app}\AirSlide.exe"; Description: "{cm:LaunchProgram,AirSlide}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
