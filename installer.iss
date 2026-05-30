; Установщик Vasya Launcher (Inno Setup)
; Собирает папку onedir (dist_v109\Launcher) в один Setup.exe
; с мастером установки, выбором директории, прогресс-баром, ярлыками и деинсталлятором.

#define MyAppName "Vasya Launcher"
#define MyAppVersion "1.0.10"
#define MyAppPublisher "vasya_pechen"
#define MyAppExeName "Launcher.exe"
#define MySource "dist_v109\Launcher"

[Setup]
; Уникальный идентификатор приложения (для записи в «Установка и удаление программ»)
AppId={{8C762944-32B4-41AF-AC23-70C6BD7A2B3A}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Ставим в Program Files (требуются права администратора).
PrivilegesRequired=admin
DefaultDirName={autopf}\VasyaLauncher
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist_installer
OutputBaseFilename=VasyaLauncher-Setup-{#MyAppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MySource}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
