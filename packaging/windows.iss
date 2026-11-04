; Установщик для Windows (Inno Setup 6). Сборка: iscc packaging\windows.iss  — после PyInstaller (dist\VacancyAssistant).
; Ставится без прав администратора — в папку пользователя; ярлыки в меню «Пуск» и на рабочем столе.
#define AppName "Помощник по вакансиям"
; Номер версии передаёт сборка (build.yml): iscc /DAppVersion=… — из vacancy_assistant/__init__.py
#ifndef AppVersion
  #define AppVersion "dev"
#endif

[Setup]
AppId={{6E0B7C1A-4C2E-4C8B-9E55-7A3D2B1F0A11}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\VacancyAssistant
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=VacancyAssistant-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon\icon.ico
UninstallDisplayIcon={app}\VacancyAssistant.exe
DisableProgramGroupPage=yes

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
Source: "..\dist\VacancyAssistant\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "Как установить на Windows.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\VacancyAssistant.exe"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\VacancyAssistant.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VacancyAssistant.exe"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent
