@echo off
title Install Requirements
echo Installing packages from requirements.txt...

pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo There was an error installing the requirements.
) else (
    echo.
    echo Successfully installed all requirements!
)

pause