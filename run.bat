@echo off
where pythonw >nul 2>nul
if errorlevel 1 (
  start "" /normal python "%~dp0revenue_app.pyw"
) else (
  start "" /normal pythonw "%~dp0revenue_app.pyw"
)

