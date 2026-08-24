@echo off
title TRAE Real Token Usage - Debug Console
cd /d "%~dp0"

echo ============================================================
echo   TRAE Real Token Usage MCP Server (debug console)
echo ============================================================
echo.
echo  Normally you do NOT need to run this file manually.
echo  The server is auto-started by TRAE as an MCP subprocess.
echo  This console is for viewing background logs only.
echo.
echo  Press Ctrl+C to quit.
echo.

python server\mcp_server.py
echo.
echo [server exited] Press any key to close this window...
pause >nul
