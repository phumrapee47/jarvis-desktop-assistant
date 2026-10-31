param([string]$Text, [string]$Out)
# เสียงพูดสำรองแบบออฟไลน์ (Windows OneCore, เช่น Microsoft Pattara ภาษาไทย) ใช้เมื่อ edge-tts ล้มทุกครั้ง
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$v = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.Language -like 'th*' } | Select-Object -First 1
if (-not $v) { Write-Error "no Thai voice"; exit 2 }
$synth.Voice = $v
$stream = Await ($synth.SynthesizeTextToStreamAsync($Text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$in = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
$fs = [System.IO.File]::Create($Out); $in.CopyTo($fs); $fs.Close()
