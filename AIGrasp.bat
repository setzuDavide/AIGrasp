@echo off
rem Opens AIGrasp in the browser.
rem   Double click           -> the last repository you looked at
rem   AIGrasp.bat C:\repo -> that repository (you can also drag a folder onto this file)
python "%~dp0aigrasp.py" %*
if errorlevel 1 pause
