@echo off
powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0deploy-to-kodi.ps1" -Watch
