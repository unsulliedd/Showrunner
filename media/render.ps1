# Renders the media pages to images with Microsoft Edge (Windows only):
#   powershell -ExecutionPolicy Bypass -File media/render.ps1 [-Shots <folder>]
# The README images and the social preview show screenshots of the app, taken at the sizes the pages give in
# data-width and data-height with a device scale of 2. They are read from -Shots, media/shots by default, and are not
# kept in the repository. make_shots.py takes them.
param([string]$Shots = (Join-Path $PSScriptRoot "shots"))
$ErrorActionPreference = "Stop"
$edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
$media = $PSScriptRoot
$userData = Join-Path $env:TEMP "showrunner-media-render"
$shotsUrl = [uri]::EscapeDataString(([uri]((Resolve-Path $Shots).Path + "\")).AbsoluteUri)

function Render($page, $w, $h, $out, $scale = 1) {
  $url = "file:///" + (Join-Path $media $page).Replace("\", "/") + "?shots=$shotsUrl"
  $flags = @("--headless=new", "--disable-gpu", "--hide-scrollbars", "--user-data-dir=$userData", "--force-device-scale-factor=$scale",
    "--window-size=$w,$h", "--virtual-time-budget=5000", "--screenshot=$out", $url)
  Start-Process -FilePath $edge -ArgumentList $flags -Wait -WindowStyle Hidden
}

foreach ($image in @(@("hero", 1280, 640), @("overview", 1280, 800), @("tracks", 1280, 800), @("names", 1280, 800), @("review", 1280, 800))) {
  Render "$($image[0]).html" $image[1] $image[2] (Join-Path $media "$($image[0]).png") 2
}
Render "social.html" 1280 640 (Join-Path $media "social.png") 1
Render "social.html" 1280 640 (Join-Path $media "social-2k.png") 2
