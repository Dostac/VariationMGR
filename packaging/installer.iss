; ============================================================================
; VirtualBuilders - Variation Manager Installer
; Requires Inno Setup 6+  (https://jrsoftware.org/isinfo.php)
; ============================================================================

#define AppName      "VirtualBuilders VariationMGR"
#define AppPublisher "VirtualBuilders"
#define AppVersion   "1.0.0"
#define AppURL       "https://virtualbuilders.com"

[Setup]
AppId={{B3A2F1E0-7C4D-4E5A-9F1B-2D3E4F5A6B7C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\VirtualBuilders\VariationMGR
DefaultGroupName={#AppPublisher}
OutputDir=dist
OutputBaseFilename=VB_VariationMGR_Setup_{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
UninstallDisplayName={#AppName}
SetupIconFile=compiler:SetupClassicIcon.ico

[Types]
Name: "full";    Description: "Full installation (Plugin + Server + Worker)"
Name: "plugin";  Description: "Plugin only (3ds Max integration)"
Name: "custom";  Description: "Custom"; Flags: iscustom

[Components]
Name: "plugin";  Description: "Variation Manager && Batch Renderer (3ds Max plugin)"; Types: full plugin custom; Flags: fixed
Name: "server";  Description: "Network Render Server";                                Types: full custom
Name: "worker";  Description: "Network Render Worker";                                Types: full custom

; ============================================================================
; Files
; ============================================================================

[Files]
; Plugin files (staged by build_plugin.py)
Source: "staging\plugin\*"; DestDir: "{app}\plugin"; Components: plugin; Flags: ignoreversion recursesubdirs createallsubdirs

; Server
Source: "dist\Server\*"; DestDir: "{app}\Server"; Components: server; Flags: ignoreversion recursesubdirs createallsubdirs

; Worker
Source: "dist\Worker\*"; DestDir: "{app}\Worker"; Components: worker; Flags: ignoreversion recursesubdirs createallsubdirs

; Macroscript template — copied to app dir, then placed per-Max-version by [Code]
Source: "VB_VariationMGR.mcr"; DestDir: "{app}"; Flags: ignoreversion; Components: plugin

; Version marker
Source: "version.txt"; DestDir: "{app}"; Flags: ignoreversion; Check: CreateVersionFile

[Icons]
Name: "{group}\Server Dashboard"; Filename: "{app}\Server\Server.exe"; Parameters: "--ui"; Components: server
Name: "{group}\Worker Dashboard";  Filename: "{app}\Worker\Worker.exe";  Components: worker
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; ============================================================================
; Pascal Script — detect 3ds Max versions and install macroscript
; ============================================================================

[Code]

type
  TMaxVersion = record
    Year: String;
    InstallDir: String;
  end;

var
  MaxVersions: array of TMaxVersion;
  MaxCheckListBox: TNewCheckListBox;
  MaxPage: TWizardPage;

function CreateVersionFile: Boolean;
begin
  { Write a version.txt into the staging area so Inno picks it up. }
  SaveStringToFile(ExpandConstant('{tmp}\version.txt'), '{#AppVersion}', False);
  Result := True;
end;

procedure DetectMaxVersions;
var
  InternalVers: array of String;
  DisplayYears: array of String;
  I: Integer;
  InstallDir: String;
  RegKey: String;
  Count: Integer;
begin
  { Registry uses internal version numbers, not years.
    26.0 = 2024, 27.0 = 2025, 28.0 = 2026, 29.0 = 2027. }
  SetArrayLength(InternalVers, 4);
  SetArrayLength(DisplayYears, 4);
  InternalVers[0] := '26.0';  DisplayYears[0] := '2024';
  InternalVers[1] := '27.0';  DisplayYears[1] := '2025';
  InternalVers[2] := '28.0';  DisplayYears[2] := '2026';
  InternalVers[3] := '29.0';  DisplayYears[3] := '2027';

  Count := 0;
  SetArrayLength(MaxVersions, Length(InternalVers));

  for I := 0 to Length(InternalVers) - 1 do
  begin
    RegKey := 'SOFTWARE\Autodesk\3dsMax\' + InternalVers[I];
    if RegQueryStringValue(HKLM, RegKey, 'Installdir', InstallDir) then
    begin
      if DirExists(InstallDir) then
      begin
        MaxVersions[Count].Year := DisplayYears[I];
        MaxVersions[Count].InstallDir := InstallDir;
        Count := Count + 1;
      end;
    end;
  end;

  SetArrayLength(MaxVersions, Count);
end;

procedure CreateMaxSelectionPage;
var
  I: Integer;
begin
  MaxPage := CreateCustomPage(wpSelectComponents,
    '3ds Max Integration',
    'Select which 3ds Max installations should receive the macroscript.');

  MaxCheckListBox := TNewCheckListBox.Create(MaxPage);
  MaxCheckListBox.Parent := MaxPage.Surface;
  MaxCheckListBox.Left := 0;
  MaxCheckListBox.Top := 0;
  MaxCheckListBox.Width := MaxPage.SurfaceWidth;
  MaxCheckListBox.Height := MaxPage.SurfaceHeight;
  MaxCheckListBox.Flat := True;

  if GetArrayLength(MaxVersions) = 0 then
  begin
    MaxCheckListBox.AddCheckBox('No 3ds Max installations detected', '', 0, False, False, False, False, nil);
    MaxCheckListBox.ItemEnabled[0] := False;
  end
  else
  begin
    for I := 0 to GetArrayLength(MaxVersions) - 1 do
    begin
      MaxCheckListBox.AddCheckBox(
        '3ds Max ' + MaxVersions[I].Year,
        MaxVersions[I].InstallDir,
        0, True, True, False, False, nil);
    end;
  end;
end;

function PatchMcrInstallDir(const SrcPath, InstallDir: String): String;
var
  Content: AnsiString;
  S: String;
begin
  { Read the template .mcr and replace the placeholder install path. }
  LoadStringFromFile(SrcPath, Content);
  S := String(Content);
  StringChangeEx(S,
    'C:\Program Files\VirtualBuilders\VariationMGR\plugin',
    InstallDir + '\plugin',
    True);
  Result := S;
end;

procedure InstallMacroscripts;
var
  I: Integer;
  MacroDir: String;
  McrSrc: String;
  McrContent: String;
  DestPath: String;
  AppDir: String;
begin
  McrSrc := ExpandConstant('{app}\VB_VariationMGR.mcr');
  AppDir := ExpandConstant('{app}');

  for I := 0 to GetArrayLength(MaxVersions) - 1 do
  begin
    if MaxCheckListBox.Checked[I] then
    begin
      MacroDir := MaxVersions[I].InstallDir + '\MacroScripts';
      if not DirExists(MacroDir) then
        ForceDirectories(MacroDir);

      McrContent := PatchMcrInstallDir(McrSrc, AppDir);
      DestPath := MacroDir + '\VB_VariationMGR.mcr';
      SaveStringToFile(DestPath, McrContent, False);
      Log('Installed macroscript: ' + DestPath);
    end;
  end;
end;

procedure RemoveMacroscripts;
var
  InternalVers: array of String;
  I: Integer;
  InstallDir, McrPath: String;
  RegKey: String;
begin
  SetArrayLength(InternalVers, 4);
  InternalVers[0] := '26.0';
  InternalVers[1] := '27.0';
  InternalVers[2] := '28.0';
  InternalVers[3] := '29.0';

  for I := 0 to Length(InternalVers) - 1 do
  begin
    RegKey := 'SOFTWARE\Autodesk\3dsMax\' + InternalVers[I];
    if RegQueryStringValue(HKLM, RegKey, 'Installdir', InstallDir) then
    begin
      McrPath := InstallDir + '\MacroScripts\VB_VariationMGR.mcr';
      if FileExists(McrPath) then
      begin
        DeleteFile(McrPath);
        Log('Removed macroscript: ' + McrPath);
      end;
    end;
  end;
end;

procedure InitializeWizard;
begin
  DetectMaxVersions;
  CreateMaxSelectionPage;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { Skip the Max selection page if the plugin component is not selected. }
  if (MaxPage <> nil) and (PageID = MaxPage.ID) then
    Result := not WizardIsComponentSelected('plugin')
  else
    Result := False;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsComponentSelected('plugin') then
      InstallMacroscripts;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveMacroscripts;
end;
