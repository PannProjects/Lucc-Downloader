# ============================================================
# DOCKERFILE untuk Hugging Face Spaces
# ============================================================
# 
# KENAPA PAKAI DOCKER (bukan Gradio/Streamlit)?
# - Kita sudah punya kode Flask yang jadi, tidak perlu tulis ulang
# - Docker memberikan kontrol penuh atas environment
# - Bisa install FFmpeg dan library system lainnya
# - Flask + Bootstrap 5 UI kita bisa langsung dipakai
#
# Hugging Face Spaces gratis dan TIDAK butuh kartu kredit!
# ============================================================

# Base image: Python 3.10 slim (lebih ringan)
FROM python:3.10-slim

# ============================================================
# INSTALL SYSTEM DEPENDENCIES
# ============================================================

# Update package list dan install FFmpeg
# FFmpeg WAJIB ada untuk:
# - Konversi video ke MP3 (audio extraction)
# - Merge video + audio dari YouTube
# - Proses berbagai format video
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# SETUP WORKING DIRECTORY DAN PERMISSION
# ============================================================

# Set working directory
WORKDIR /app

# Buat folder downloads dengan permission penuh
# chmod 777 = semua user bisa read, write, execute
RUN mkdir -p /app/downloads && chmod 777 /app/downloads

# Buat folder templates
RUN mkdir -p /app/templates

# ============================================================
# INSTALL PYTHON DEPENDENCIES
# ============================================================

# Copy requirements.txt terlebih dahulu (untuk caching Docker layer)
COPY requirements.txt .

# Install Python packages secara GLOBAL (bukan user-specific)
# --no-cache-dir = hemat space
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================
# COPY APPLICATION FILES
# ============================================================

# Copy semua file aplikasi
COPY app.py .
COPY templates/ ./templates/

# ============================================================
# SETUP USER (untuk keamanan)
# ============================================================

# Buat user non-root
RUN useradd -m -u 1000 appuser

# Set permission untuk folder app
RUN chown -R appuser:appuser /app

# Switch ke non-root user
USER appuser

# ============================================================
# RUN APPLICATION
# ============================================================

# Expose port 7860 (standar Hugging Face Spaces)
EXPOSE 7860

# Jalankan aplikasi dengan Python + Gunicorn
# Menggunakan full path ke gunicorn untuk memastikan ditemukan
CMD ["python", "-m", "gunicorn", "app:app", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "120"]
