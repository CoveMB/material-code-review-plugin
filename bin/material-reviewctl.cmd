@echo off
setlocal
set "ROOT=%~dp0.."
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%ROOT%\skills\material-code-review\scripts\reviewctl.py" %*
  exit /b %ERRORLEVEL%
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%ROOT%\skills\material-code-review\scripts\reviewctl.py" %*
  exit /b %ERRORLEVEL%
)
echo material-reviewctl requires Python 3.10 or newer 1>&2
exit /b 127
