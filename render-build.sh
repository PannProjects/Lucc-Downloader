#!/usr/bin/env bash
# ============================================================
# RENDER BUILD SCRIPT
# ============================================================
# Script ini dijalankan otomatis oleh Render.com saat proses build.
# Tujuan: Install FFmpeg di server karena Render tidak punya FFmpeg bawaan.
#
# KENAPA FFmpeg PENTING?
# - Untuk konversi video ke MP3 (audio)
# - Untuk merge video + audio dari YouTube (YouTube pisahkan stream)
# - Tanpa FFmpeg, fitur download MP3 tidak akan bekerja!
# ============================================================

echo "=========================================="
echo "🔧 Installing FFmpeg..."
echo "=========================================="

# Install FFmpeg menggunakan apt-get
# Render menggunakan Ubuntu, jadi kita pakai apt-get
apt-get update && apt-get install -y ffmpeg

# Verifikasi instalasi berhasil
echo "=========================================="
echo "✅ FFmpeg installed successfully!"
echo "=========================================="
ffmpeg -version

echo "=========================================="
echo "📦 Installing Python dependencies..."
echo "=========================================="

# Install semua library Python dari requirements.txt
pip install -r requirements.txt

echo "=========================================="
echo "🚀 Build complete!"
echo "=========================================="
