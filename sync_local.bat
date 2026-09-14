@echo off
chcp 65001 >nul
title WeChat to Obsidian 本地同步

echo ======================================================
echo    正在拉取云端微信笔记并落盘到 Obsidian Vault...
echo ======================================================

python "%~dp0local\sync.py" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] 同步过程中发生异常。
) else (
    echo.
    echo [完成] 同步完成！
)

echo.
pause
