@echo off
chcp 65001 >nul
title YiXianPai spawn injector
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

tasklist /fi "imagename eq YiXianPai.exe" 2>nul | find /i "YiXianPai.exe" >nul
if not errorlevel 1 goto running

echo ================================================================
echo  Launching YiXianPai via frida + injecting the protocol hook
echo  (hook is installed BEFORE frame 1 = card counts correct from round 1)
echo  The game starts by itself. Press Ctrl-C in THIS window to stop.
echo ================================================================
echo.
"C:\Users\zd117\anaconda3\python.exe" "%~dp0spawn_launcher.py"
goto done

:running
echo [!] YiXianPai is already running.
echo     Close the game completely, then double-click this file again.

:done
echo.
echo [launcher exited] Press any key to close this window.
pause >nul
