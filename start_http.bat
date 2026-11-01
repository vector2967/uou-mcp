@echo off
rem UOU MCP local server: http://127.0.0.1:44610/mcp  (close this window to stop)
cd /d "%~dp0"
uv run uou-mcp --http 44610
pause
