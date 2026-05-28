; Award Tracker - Premium Setup Script
; For compiling with Inno Setup Compiler (ISCC)

[Setup]
AppName=Award Tracker
AppVersion=1.1.0
AppPublisher=Sunghwan Yoo
DefaultDirName={userappdata}\AwardTracker
DefaultGroupName=Award Tracker
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=awardtracker-setup
SetupIconFile=
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\awardtracker.exe
WizardStyle=modern

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
var
  CleanupUserData: Boolean;

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
      DelTree(ExpandConstant('{app}\backups'), True, True, True);
      DelTree(ExpandConstant('{app}\browser_profiles'), True, True, True);
      DelTree(ExpandConstant('{app}\downloaded_files'), True, True, True);
      DeleteFile(ExpandConstant('{app}\awardtracker.db'));
      DeleteFile(ExpandConstant('{app}\scraper_debug.log'));
      DeleteFile(ExpandConstant('{app}\settings.json'));
      DeleteFile(ExpandConstant('{app}\valuations.json'));
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

