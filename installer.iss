; Award Tracker - Premium Setup Script
; For compiling with Inno Setup Compiler (ISCC)

#define FileHandle FileOpen(SourcePath + "\version.txt")
#define AppVersion FileRead(FileHandle)
#expr FileClose(FileHandle)

[Setup]
AppName=Award Tracker
AppVersion={#AppVersion}
AppPublisher=Sunghwan Yoo
DefaultDirName={code:GetDefaultDirName}
UsePreviousAppDir=no
DirExistsWarning=no
DefaultGroupName=Award Tracker
DisableProgramGroupPage=yes
DisableDirPage=no
OutputDir=dist
OutputBaseFilename=awardtracker-win64-setup
SetupIconFile=awardtracker.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
UninstallDisplayIcon={app}\awardtracker.exe
WizardStyle=modern

[InstallDelete]
Type: files; Name: "{userappdata}\AwardTracker\awardtracker.exe"
Type: files; Name: "{userappdata}\AwardTracker\unins000.exe"
Type: files; Name: "{userappdata}\AwardTracker\unins000.dat"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\Award Tracker_is1"; Flags: deletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\AwardTracker_is1"; Flags: deletekey

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\awardtracker.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Award Tracker"; Filename: "{app}\awardtracker.exe"
Name: "{group}\{cm:UninstallProgram,Award Tracker}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Award Tracker"; Filename: "{app}\awardtracker.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\awardtracker.exe"; Description: "{cm:LaunchProgram,Award Tracker}"; Flags: nowait postinstall skipifsilent

[Code]
function ExtractDirFromUninstallString(UninstStr: String): String;
var
  PosExe: Integer;
begin
  Result := UninstStr;
  if (Length(Result) > 0) and (Result[1] = '"') then
  begin
    Delete(Result, 1, 1);
  end;
  if (Length(Result) > 0) and (Result[Length(Result)] = '"') then
  begin
    Delete(Result, Length(Result), 1);
  end;
  PosExe := Pos('\unins', LowerCase(Result));
  if PosExe > 0 then
  begin
    Result := Copy(Result, 1, PosExe - 1);
  end;
end;

function CheckRegistryForPrevPath(RootKey: Integer; SubKeyName: String; var Path: String): Boolean;
var
  UninstStr: String;
  CleanPath: String;
  UserAppData: String;
begin
  Result := False;
  if RegQueryStringValue(RootKey, SubKeyName, 'UninstallString', UninstStr) then
  begin
    if UninstStr <> '' then
    begin
      CleanPath := ExtractDirFromUninstallString(UninstStr);
      if CleanPath <> '' then
      begin
        UserAppData := ExpandConstant('{userappdata}');
        if Pos(UserAppData, CleanPath) = 0 then
        begin
          Path := CleanPath;
          Result := True;
        end;
      end;
    end;
  end;
end;

function GetDefaultDirName(Param: String): String;
var
  PrevPath: String;
begin
  if CheckRegistryForPrevPath(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\AwardTracker_is1', PrevPath) then
  begin
    Result := PrevPath;
    Exit;
  end;
  if CheckRegistryForPrevPath(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Award Tracker_is1', PrevPath) then
  begin
    Result := PrevPath;
    Exit;
  end;
  if CheckRegistryForPrevPath(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\AwardTracker_is1', PrevPath) then
  begin
    Result := PrevPath;
    Exit;
  end;
  if CheckRegistryForPrevPath(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Award Tracker_is1', PrevPath) then
  begin
    Result := PrevPath;
    Exit;
  end;
  Result := ExpandConstant('{autopf}\AwardTracker');
end;

var
  CleanupUserData: Boolean;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OldVal: String;
begin
  if CurStep = ssPostInstall then
  begin
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'AwardTracker', OldVal) then
    begin
      RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'AwardTracker', '"' + ExpandConstant('{app}\awardtracker.exe') + '" --startup');
    end;
  end;
end;

procedure InitializeUninstallProgressForm();
var
  CustomForm: TSetupForm;
  PromptLabel: TNewStaticText;
  CleanupCheckbox: TNewCheckBox;
  OKButton: TNewButton;
begin
  CleanupUserData := False;
  
  // If running silently, do not show any UI and do not delete data
  if UninstallSilent() then
  begin
    Exit;
  end;

  CustomForm := CreateCustomForm(ScaleX(400), ScaleY(160), True, True);
  try
    CustomForm.Caption := 'Data Cleanup Options';
    CustomForm.Position := poScreenCenter;
    
    PromptLabel := TNewStaticText.Create(CustomForm);
    PromptLabel.Parent := CustomForm;
    PromptLabel.Left := ScaleX(20);
    PromptLabel.Top := ScaleY(20);
    PromptLabel.Width := ScaleX(360);
    PromptLabel.Height := ScaleY(35);
    PromptLabel.Caption := 'Do you want to delete your points database, browser profiles, and logs? (This cannot be undone)';
    PromptLabel.WordWrap := True;
    
    CleanupCheckbox := TNewCheckBox.Create(CustomForm);
    CleanupCheckbox.Parent := CustomForm;
    CleanupCheckbox.Left := ScaleX(20);
    CleanupCheckbox.Top := ScaleY(65);
    CleanupCheckbox.Width := ScaleX(360);
    CleanupCheckbox.Height := ScaleY(20);
    CleanupCheckbox.Caption := 'Yes, delete database, browser profiles, and logs';
    CleanupCheckbox.Checked := False;
    
    OKButton := TNewButton.Create(CustomForm);
    OKButton.Parent := CustomForm;
    OKButton.Left := ScaleX(290);
    OKButton.Top := ScaleY(100);
    OKButton.Width := ScaleX(90);
    OKButton.Height := ScaleY(30);
    OKButton.Caption := 'Continue';
    OKButton.ModalResult := mrOk;
    OKButton.Default := True;
    
    CustomForm.ShowModal();
    CleanupUserData := CleanupCheckbox.Checked;
  finally
    CustomForm.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if CleanupUserData then
    begin
      // Delete the dynamically created folders and files
      DelTree(ExpandConstant('{userappdata}\AwardTracker\backups'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\AwardTracker\browser_profiles'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\AwardTracker\downloaded_files'), True, True, True);
      DeleteFile(ExpandConstant('{userappdata}\AwardTracker\awardtracker.db'));
      DeleteFile(ExpandConstant('{userappdata}\AwardTracker\scraper_debug.log'));
      DelTree(ExpandConstant('{userappdata}\AwardTracker\logs'), True, True, True);
      DeleteFile(ExpandConstant('{userappdata}\AwardTracker\settings.json'));
      DeleteFile(ExpandConstant('{userappdata}\AwardTracker\valuations.json'));
    end;
  end;
end;

function InitializeUninstall(): Boolean;
var
  ErrorCode: Integer;
begin
  // Force close any running awardtracker.exe processes before uninstallation starts
  Exec('taskkill.exe', '/f /im awardtracker.exe', '', SW_HIDE, ewWaitUntilTerminated, ErrorCode);
  Result := True;
end;

