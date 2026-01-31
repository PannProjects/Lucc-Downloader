"""
Universal Video Downloader - Flask Backend
==========================================
Aplikasi web untuk mengunduh video dari berbagai platform:
YouTube, TikTok, Instagram, Facebook, Twitter

Engine: yt-dlp (library download multi-platform)

PRODUCTION MODE:
- Menggunakan folder /tmp untuk penyimpanan sementara (ephemeral storage)
- File otomatis dihapus setelah dikirim ke user
- FFmpeg path dibaca dari environment variable atau default system
"""

import os
import re
import tempfile
import threading
import time
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
import yt_dlp

# ============================================================
# KONFIGURASI APLIKASI
# ============================================================

app = Flask(__name__)

# ============================================================
# DETEKSI ENVIRONMENT (LOCAL vs PRODUCTION)
# ============================================================

# Cek apakah di Hugging Face Spaces, Render.com, atau lokal
# SPACE_ID = environment variable yang ada di Hugging Face Spaces
# RENDER = environment variable yang ada di Render.com
IS_HUGGINGFACE = os.environ.get('SPACE_ID', False)
IS_RENDER = os.environ.get('RENDER', False)
IS_PRODUCTION = IS_HUGGINGFACE or IS_RENDER

if IS_HUGGINGFACE:
    # HUGGING FACE SPACES MODE
    # Folder /app/downloads sudah dibuat di Dockerfile dengan chmod 777
    DOWNLOAD_FOLDER = '/app/downloads'
    # FFmpeg diinstall via Dockerfile
    FFMPEG_PATH = '/usr/bin/ffmpeg'
    print("🤗 Running in HUGGING FACE SPACES mode")
elif IS_RENDER:
    # RENDER.COM MODE
    DOWNLOAD_FOLDER = '/tmp/downloads'
    FFMPEG_PATH = '/usr/bin/ffmpeg'
    print("🚀 Running in RENDER.COM mode")
else:
    # LOCAL MODE (Development)
    DOWNLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
    # Path FFmpeg lokal (sesuaikan dengan instalasi Anda)
    FFMPEG_PATH = r'C:\tools\ffmpeg.exe'
    print("💻 Running in LOCAL mode (Development)")

# Buat folder downloads jika belum ada
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

print(f"📁 Download folder: {DOWNLOAD_FOLDER}")
print(f"🔧 FFmpeg path: {FFMPEG_PATH}")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def sanitize_filename(filename):
    """
    Membersihkan nama file dari karakter yang tidak valid.
    Karakter seperti / \\ : * ? " < > | tidak diperbolehkan.
    """
    # Hapus karakter tidak valid
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Batasi panjang nama file
    return filename[:200] if len(filename) > 200 else filename


def delete_file_later(filepath, delay=60):
    """
    Menghapus file setelah delay tertentu (dalam detik).
    Digunakan untuk membersihkan file setelah dikirim ke user.
    
    KENAPA PERLU HAPUS FILE?
    - Server Render punya storage terbatas
    - File di /tmp akan hilang saat restart, tapi kita tetap perlu bersihkan
    - Mencegah disk space penuh
    
    Parameters:
    - filepath: Path lengkap ke file yang akan dihapus
    - delay: Waktu tunggu sebelum hapus (default 60 detik)
    """
    def delete():
        time.sleep(delay)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                print(f"🗑️ Deleted: {filepath}")
        except Exception as e:
            print(f"⚠️ Failed to delete {filepath}: {e}")
    
    # Jalankan di background thread agar tidak block response
    thread = threading.Thread(target=delete)
    thread.daemon = True  # Thread akan mati saat app berhenti
    thread.start()


def cleanup_old_files():
    """
    Membersihkan file yang sudah lama di folder downloads.
    File lebih dari 10 menit akan dihapus.
    """
    try:
        current_time = time.time()
        for filename in os.listdir(DOWNLOAD_FOLDER):
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            if os.path.isfile(filepath):
                file_age = current_time - os.path.getmtime(filepath)
                # Hapus file yang lebih dari 10 menit (600 detik)
                if file_age > 600:
                    os.remove(filepath)
                    print(f"🗑️ Cleanup: Deleted old file {filename}")
    except Exception as e:
        print(f"⚠️ Cleanup error: {e}")


def get_video_info(url):
    """
    Mengambil informasi video dari URL:
    - Judul video
    - Thumbnail
    - Daftar format/resolusi yang tersedia
    
    Return: dict dengan info video atau error message
    """
    # Opsi yt-dlp untuk mengambil info saja (tanpa download)
    ydl_opts = {
        'quiet': True,              # Mode silent, tidak print ke console
        'no_warnings': True,        # Tidak tampilkan warning
        'extract_flat': False,      # Extract info lengkap
        'ffmpeg_location': FFMPEG_PATH,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info tanpa download
            info = ydl.extract_info(url, download=False)
            
            # Ambil daftar format yang tersedia
            formats = []
            seen_resolutions = set()  # Untuk menghindari duplikat
            
            if 'formats' in info:
                for f in info['formats']:
                    # Filter hanya format video dengan resolusi
                    if f.get('height') and f.get('vcodec') != 'none':
                        resolution = f"{f['height']}p"
                        
                        # Hindari duplikat resolusi
                        if resolution not in seen_resolutions:
                            seen_resolutions.add(resolution)
                            formats.append({
                                'format_id': f.get('format_id', ''),
                                'resolution': resolution,
                                'height': f['height'],
                                'ext': f.get('ext', 'mp4'),
                                'filesize': f.get('filesize') or f.get('filesize_approx', 0)
                            })
            
            # Sort berdasarkan resolusi (tertinggi dulu)
            formats.sort(key=lambda x: x['height'], reverse=True)
            
            # Jika tidak ada format terdeteksi, tambahkan default
            if not formats:
                formats.append({
                    'format_id': 'best',
                    'resolution': 'Best Quality',
                    'height': 0,
                    'ext': 'mp4',
                    'filesize': 0
                })
            
            return {
                'success': True,
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'formats': formats
            }
            
    except yt_dlp.DownloadError as e:
        return {
            'success': False,
            'error': f'Link tidak valid atau tidak didukung: {str(e)}'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Terjadi kesalahan: {str(e)}'
        }


def download_video(url, format_type='mp4', resolution='best'):
    """
    Download video dari URL dengan format dan resolusi yang dipilih.
    
    Parameters:
    - url: Link video
    - format_type: 'mp4' untuk video, 'mp3' untuk audio only
    - resolution: Resolusi video (contoh: '720p', '1080p', 'best')
    
    Return: Path ke file yang didownload atau error message
    """
    # Bersihkan file-file lama sebelum download baru
    cleanup_old_files()
    
    try:
        # Ambil info video terlebih dahulu untuk nama file
        with yt_dlp.YoutubeDL({'quiet': True, 'ffmpeg_location': FFMPEG_PATH}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = sanitize_filename(info.get('title', 'video'))
        
        # Tentukan output template
        if format_type == 'mp3':
            # Download sebagai audio MP3
            output_file = os.path.join(DOWNLOAD_FOLDER, f'{title}.mp3')
            ydl_opts = {
                'format': 'bestaudio/best',     # Ambil audio terbaik
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'{title}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'ffmpeg_location': FFMPEG_PATH,
                # Post-processor untuk konversi ke MP3
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',    # Ekstrak audio
                    'preferredcodec': 'mp3',        # Konversi ke MP3
                    'preferredquality': '192',      # Bitrate 192kbps
                }],
            }
        else:
            # Download sebagai video MP4
            output_file = os.path.join(DOWNLOAD_FOLDER, f'{title}.mp4')
            
            # Tentukan format berdasarkan resolusi
            if resolution == 'best' or resolution == 'Best Quality':
                format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            else:
                # Parse resolusi (contoh: '720p' -> 720)
                height = resolution.replace('p', '')
                format_spec = f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best'
            
            ydl_opts = {
                'format': format_spec,
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'{title}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'ffmpeg_location': FFMPEG_PATH,
                # Merge video + audio jadi MP4
                'merge_output_format': 'mp4',
            }
        
        # Jalankan download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Cari file hasil download
        if format_type == 'mp3':
            final_file = os.path.join(DOWNLOAD_FOLDER, f'{title}.mp3')
        else:
            final_file = os.path.join(DOWNLOAD_FOLDER, f'{title}.mp4')
        
        if os.path.exists(final_file):
            return {'success': True, 'file': final_file, 'filename': os.path.basename(final_file)}
        else:
            # Coba cari file dengan extension lain
            for ext in ['mp4', 'webm', 'mkv', 'mp3', 'm4a']:
                alt_file = os.path.join(DOWNLOAD_FOLDER, f'{title}.{ext}')
                if os.path.exists(alt_file):
                    return {'success': True, 'file': alt_file, 'filename': os.path.basename(alt_file)}
            
            return {'success': False, 'error': 'File tidak ditemukan setelah download'}
            
    except yt_dlp.DownloadError as e:
        return {'success': False, 'error': f'Gagal download: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'Terjadi kesalahan: {str(e)}'}


# ============================================================
# ROUTES
# ============================================================

@app.route('/')
def index():
    """
    Route utama - Menampilkan halaman index.html
    """
    return render_template('index.html')


@app.route('/get-info', methods=['POST'])
def get_info():
    """
    Route untuk mengambil informasi video via AJAX.
    
    Request JSON:
    - url: Link video yang ingin dicek
    
    Response JSON:
    - success: Boolean
    - title: Judul video
    - thumbnail: URL thumbnail
    - formats: List resolusi yang tersedia
    - error: Pesan error (jika gagal)
    """
    # Ambil data dari request
    data = request.get_json()
    
    # Validasi: pastikan URL diberikan
    if not data or 'url' not in data:
        return jsonify({
            'success': False,
            'error': 'URL tidak boleh kosong!'
        }), 400
    
    url = data['url'].strip()
    
    # Validasi: pastikan URL tidak kosong
    if not url:
        return jsonify({
            'success': False,
            'error': 'URL tidak boleh kosong!'
        }), 400
    
    # Ambil info video
    result = get_video_info(url)
    
    return jsonify(result)


@app.route('/download', methods=['POST'])
def download():
    """
    Route untuk memproses download video.
    
    Request JSON:
    - url: Link video
    - format: 'mp3' atau 'mp4'
    - resolution: Resolusi yang dipilih (contoh: '720p')
    
    Response: File untuk didownload atau JSON error
    """
    data = request.get_json()
    
    # Validasi input
    if not data or 'url' not in data:
        return jsonify({
            'success': False,
            'error': 'URL tidak boleh kosong!'
        }), 400
    
    url = data['url'].strip()
    format_type = data.get('format', 'mp4')
    resolution = data.get('resolution', 'best')
    
    # Proses download
    result = download_video(url, format_type, resolution)
    
    if result['success']:
        filepath = result['file']
        
        # PRODUCTION: Jadwalkan penghapusan file setelah dikirim
        # File akan dihapus 60 detik setelah response dikirim
        if IS_PRODUCTION:
            delete_file_later(filepath, delay=60)
        
        # Kirim file ke browser untuk didownload
        try:
            return send_file(
                filepath,
                as_attachment=True,                    # Force download, bukan preview
                download_name=result['filename']       # Nama file saat didownload
            )
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Gagal mengirim file: {str(e)}'
            }), 500
    else:
        return jsonify(result), 400


# ============================================================
# HEALTH CHECK (untuk Render.com)
# ============================================================

@app.route('/health')
def health():
    """
    Endpoint untuk health check.
    Render.com akan mengecek endpoint ini untuk memastikan app berjalan.
    """
    return jsonify({'status': 'healthy', 'message': 'App is running!'})


# ============================================================
# MAIN - Jalankan Server
# ============================================================

if __name__ == '__main__':
    print("=" * 50)
    print("🎬 Universal Video Downloader")
    print("=" * 50)
    print("🌐 Buka browser ke: http://127.0.0.1:5000")
    print("=" * 50)
    
    # Jalankan Flask development server
    # debug=True untuk auto-reload saat file berubah
    app.run(debug=True, host='127.0.0.1', port=5000)
