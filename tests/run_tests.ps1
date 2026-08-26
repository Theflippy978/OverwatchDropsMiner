Set-Location 'C:\Users\Theflippy\Documents\Code\git\OverwatchDropsMiner'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONIOENCODING = 'utf-8'
python -m pytest tests/ -q 2>&1 | Out-String
