# Build ExamBrowser.apk (native Java + WebView) WITHOUT Gradle.
# Uses Android SDK build-tools directly: aapt2 + javac + d8 + zipalign + apksigner.
# Run:  powershell -ExecutionPolicy Bypass -File build_apk.ps1

$ErrorActionPreference = "Stop"

$SDK      = "G:\AndroidSDK"
$BT       = Join-Path $SDK "build-tools\35.0.0"
$ANDROID  = Join-Path $SDK "platforms\android-35\android.jar"
$JBR      = "C:\Program Files\Android\Android Studio\jbr"

$ROOT     = $PSScriptRoot
$BUILD    = Join-Path $ROOT "build"
$OUTDIR   = Join-Path $ROOT "dist"
$MANIFEST = Join-Path $ROOT "AndroidManifest.xml"
$RES      = Join-Path $ROOT "res"
$ASSETS   = Join-Path $ROOT "assets"
$SRC      = Join-Path $ROOT "src"
$KS       = Join-Path $ROOT "debug.keystore"

$env:JAVA_HOME = $JBR
$env:PATH      = "$JBR\bin;" + $env:PATH

$aapt2     = Join-Path $BT "aapt2.exe"
$zipalign  = Join-Path $BT "zipalign.exe"
$d8        = Join-Path $BT "d8.bat"
$apksigner = Join-Path $BT "apksigner.bat"
$javac     = Join-Path $JBR "bin\javac.exe"
$keytool   = Join-Path $JBR "bin\keytool.exe"
$jar       = Join-Path $JBR "bin\jar.exe"

foreach ($t in @($aapt2, $zipalign, $d8, $apksigner, $javac, $keytool, $ANDROID)) {
    if (-not (Test-Path $t)) { throw "Missing tool: $t" }
}

if (Test-Path $BUILD) { Remove-Item -Recurse -Force $BUILD }
New-Item -ItemType Directory -Force -Path $BUILD, $OUTDIR | Out-Null
$resZip    = Join-Path $BUILD "res.zip"
$baseApk   = Join-Path $BUILD "base.apk"
$classes   = Join-Path $BUILD "classes"
$dex       = Join-Path $BUILD "dex"
$dexedApk  = Join-Path $BUILD "dexed.apk"
$aligned   = Join-Path $BUILD "aligned.apk"
$finalApk  = Join-Path $OUTDIR "ExamBrowser.apk"

Write-Host "[1/6] Compiling resources (aapt2)..."
& $aapt2 compile --dir $RES -o $resZip
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile failed" }

Write-Host "[2/6] Linking resources (aapt2 link)..."
& $aapt2 link -o $baseApk -I $ANDROID --manifest $MANIFEST $resZip -A $ASSETS `
    --version-code 1 --version-name 1.0
if ($LASTEXITCODE -ne 0) { throw "aapt2 link failed" }

Write-Host "[3/6] Compiling Java (javac)..."
New-Item -ItemType Directory -Force -Path $classes | Out-Null
$javaFiles = (Get-ChildItem -Path $SRC -Recurse -Filter *.java).FullName
& $javac -encoding UTF-8 -d $classes -classpath $ANDROID --release 11 $javaFiles
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

Write-Host "[4/6] Dexing (d8)..."
New-Item -ItemType Directory -Force -Path $dex | Out-Null
$classFiles = (Get-ChildItem -Path $classes -Recurse -Filter *.class).FullName
& $d8 --release --min-api 24 --lib $ANDROID --output $dex $classFiles
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }

Write-Host "[5/6] Packaging classes.dex into APK..."
Copy-Item $baseApk $dexedApk -Force
Push-Location $dex
& $jar uf $dexedApk classes.dex
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "jar update failed" }

& $zipalign -f 4 $dexedApk $aligned
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }

Write-Host "[6/6] Signing (apksigner)..."
if (-not (Test-Path $KS)) {
    & $keytool -genkeypair -keystore $KS -storepass android -keypass android `
        -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=Android Debug,O=Android,C=US"
    if ($LASTEXITCODE -ne 0) { throw "keytool failed" }
}
& $apksigner sign --ks $KS --ks-pass pass:android --key-pass pass:android `
    --out $finalApk $aligned
if ($LASTEXITCODE -ne 0) { throw "apksigner failed" }

$size = (Get-Item $finalApk).Length / 1KB
Write-Host ("BUILD OK -> {0} ({1:N0} KB)" -f $finalApk, $size)
