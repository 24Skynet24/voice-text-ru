; Установщик Voice Text RU (ТЗ §39).
; Сборка: ISCC.exe build\installer.iss
; Требуется Inno Setup 6: https://jrsoftware.org/isdl.php
;
; Перед запуском должен быть выполнен PyInstaller — установщик упаковывает
; готовый каталог dist\VoiceTextRU.

#define AppName "Voice Text RU"
#define AppVersion "1.0.0"
#define AppExeName "Voice Text RU.exe"
#define SourceDir "..\dist\VoiceTextRU"

[Setup]
AppId={{8F3C1A42-6B7E-4D5A-9C10-7E2B4A6D9F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\VoiceTextRU
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=VoiceTextRU-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Приложение ставится для текущего пользователя, поэтому права администратора не нужны.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\src\voicetext_ru\resources\app.ico

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Модели распознавания и журналы лежат в профиле пользователя и при удалении
; программы не трогаются намеренно: их повторная загрузка занимает время.
; Пользователь может удалить их вручную: %LOCALAPPDATA%\VoiceTextRU
