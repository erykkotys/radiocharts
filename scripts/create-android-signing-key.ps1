$ErrorActionPreference = "Stop"

$keytoolCommand = Get-Command keytool -ErrorAction SilentlyContinue
$keytoolPath = if ($keytoolCommand) { $keytoolCommand.Source } else { $null }
if (-not $keytoolPath) {
    $keytoolCandidates = @(
        $(if ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME "bin\keytool.exe" }),
        (Join-Path $env:ProgramFiles "Android\Android Studio\jbr\bin\keytool.exe"),
        (Join-Path $env:ProgramFiles "Android\Android Studio\jre\bin\keytool.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }
    $keytoolPath = $keytoolCandidates | Select-Object -First 1
}
if (-not $keytoolPath) {
    throw "Nie znaleziono keytool. Zainstaluj JDK 17 (np. Temurin) i uruchom skrypt ponownie."
}

$signingDirectory = Join-Path $env:USERPROFILE "sprawdzacz-audycji-signing"
$keyPath = Join-Path $signingDirectory "sprawdzacz-release.jks"
New-Item -ItemType Directory -Force -Path $signingDirectory | Out-Null

if (Test-Path $keyPath) {
    throw "Klucz juz istnieje: $keyPath`nNie nadpisuje go, bo utrata starego klucza uniemozliwi aktualizowanie aplikacji."
}

$securePassword = Read-Host "Ustal mocne haslo klucza (zapisz je w menedzerze hasel)" -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    if ($password.Length -lt 8) {
        throw "Haslo musi miec co najmniej 8 znakow."
    }

    & $keytoolPath `
        -genkeypair `
        -v `
        -keystore $keyPath `
        -storetype PKCS12 `
        -alias sprawdzacz `
        -keyalg RSA `
        -keysize 3072 `
        -validity 10000 `
        -storepass $password `
        -keypass $password `
        -dname "CN=Sprawdzacz Audycji, O=Radio Emaus, C=PL"
    if ($LASTEXITCODE -ne 0) {
        throw "keytool zakonczyl prace bledem $LASTEXITCODE."
    }

    [Convert]::ToBase64String([IO.File]::ReadAllBytes($keyPath)) | Set-Clipboard
}
finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    $password = $null
}

Write-Host ""
Write-Host "Gotowe. Zawartosc klucza Base64 jest w schowku."
Write-Host "Plik klucza: $keyPath"
Write-Host "Zrob jego bezpieczna kopie zapasowa. Nie dodawaj go do GitHub ani do ZIP-a projektu."
Write-Host "W GitHub utworz sekret ANDROID_KEYSTORE_BASE64 i wklej zawartosc schowka."
Write-Host "Utworz tez sekret ANDROID_KEYSTORE_PASSWORD z haslem podanym przed chwila."
