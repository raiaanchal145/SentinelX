<#
.SYNOPSIS
    Generates safe, non-destructive failed logon events (Event ID 4625) in Windows Security log.
.DESCRIPTION
    Uses .NET PrincipalContext.ValidateCredentials with an invalid test password against a dummy
    test username. This triggers genuine Windows Event ID 4625 records in the local Security Log
    without risking locking out real employee or administrator accounts.
.PARAMETER Count
    Number of failed logon attempts to generate (default: 5; use 22+ to trigger the SentinelX
    repeated-failed-logins brute force detection rule).
.PARAMETER Username
    The dummy test account name to attribute the failure to (default: SentinelXTestUser).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\agent\tools\test_failed_logon.ps1 -Count 5
    powershell -ExecutionPolicy Bypass -File .\agent\tools\test_failed_logon.ps1 -Count 25
#>

param(
    [int]$Count = 5,
    [string]$Username = "SentinelXTestUser"
)

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "SentinelX Windows Event Log Test: Event ID 4625 Generator" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "[*] Generating $Count safe failed logon attempt(s) for user '$Username'..." -ForegroundColor Yellow

Add-Type -AssemblyName System.DirectoryServices.AccountManagement

try {
    $context = New-Object System.DirectoryServices.AccountManagement.PrincipalContext(
        [System.DirectoryServices.AccountManagement.ContextType]::Machine
    )
} catch {
    Write-Warning "Could not initialize machine PrincipalContext: $_"
    $context = $null
}

$successCount = 0

for ($i = 1; $i -le $Count; $i++) {
    $wrongPassword = "SentinelX_Incorrect_Password_" + [guid]::NewGuid().ToString()

    if ($context) {
        # ValidateCredentials triggers LogonUser with LogonType 3 (Network) -> logs Event ID 4625
        $null = $context.ValidateCredentials($Username, $wrongPassword)
        $successCount++
        Write-Host "  [$i/$Count] Triggered bad logon for '$Username' ..." -ForegroundColor Gray
    } else {
        # Fallback: runas invocation with wrong password
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "runas.exe"
        $psi.Arguments = "/user:$Username cmd.exe"
        $psi.RedirectStandardInput = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true

        $proc = [System.Diagnostics.Process]::Start($psi)
        $proc.StandardInput.WriteLine($wrongPassword)
        $proc.StandardInput.Close()
        $null = $proc.WaitForExit(1000)
        $successCount++
    }

    Start-Sleep -Milliseconds 250
}

Write-Host "`n[+] Completed $successCount failed logon attempt(s)." -ForegroundColor Green
Write-Host "[*] Checking Windows Security Log for latest Event 4625..." -ForegroundColor Cyan

try {
    $latest = Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4625} -MaxEvents 1 -ErrorAction Stop
    Write-Host "[+] Found Event ID 4625 in Security Log!" -ForegroundColor Green
    Write-Host "    TimeCreated: $($latest.TimeCreated)"
    Write-Host "    RecordId:    $($latest.RecordId)"
    Write-Host "    Message:     $($latest.Message.Split("`n")[0])"
    Write-Host "`n[*] The SentinelX agent will ingest this event within 3-5 seconds." -ForegroundColor Cyan
} catch {
    Write-Host "[!] Note: Auditing for Logon Failures may be disabled in local security policy." -ForegroundColor Yellow
    Write-Host "    To enable auditing, run: auditpol /set /subcategory:`"Logon`" /failure:enable" -ForegroundColor Yellow
}

Write-Host "========================================================" -ForegroundColor Cyan
