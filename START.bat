@echo off
title Universal Video Downloader - Launcher
color 0A

echo ================================================
echo   Universal Video Downloader - Launcher
echo ================================================
echo.

:: Jalankan Flask di background
echo [1/2] Starting Flask server...
start "Flask Server" cmd /k "cd /d d:\Project\Lucc Downloader && python app.py"

:: Tunggu Flask start
timeout /t 3 /nobreak > nul

:: Jalankan ngrok
echo [2/2] Starting ngrok tunnel...
start "ngrok Tunnel" cmd /k "cd /d C:\tools && ngrok.exe http 5000"

echo.
echo ================================================
echo   DONE! Kedua service sudah berjalan.
echo ================================================
echo.
echo   - Flask: http://127.0.0.1:5000
echo   - ngrok: Lihat URL di window ngrok
echo.
echo   Tekan tombol apa saja untuk tutup launcher ini...
echo   (Flask dan ngrok tetap jalan di background)
echo ================================================
pause > nul
