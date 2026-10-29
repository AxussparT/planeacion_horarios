#define MyAppName "SAGA"
#define MyAppVersion "2.1.0"
#define MyAppPublisher "SAGA"
#define MyAppExeName "SAGA.exe"

[Setup]
AppId={{7A43701B-15E9-4A4C-989C-DA5F64A0E0B8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\SAGA
DefaultGroupName=SAGA
PrivilegesRequired=lowest
OutputDir=C:\Users\Admin\Desktop\servicioV2\servicio_S\instalador
OutputBaseFilename=SAGA-Setup-{#MyAppVersion}
SetupIconFile=C:\Users\Admin\Desktop\servicioV2\servicio_S\src\UI\SAGA.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
Uninstallable=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "C:\Users\Admin\Desktop\servicioV2\servicio_S\dist\SAGA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\src\UI\SAGA.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\src\UI\SAGA.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
