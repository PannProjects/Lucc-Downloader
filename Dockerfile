# ============================================================
# DOCKERFILE untuk Railway.app
# ============================================================

FROM python:3.10-slim

# Install FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create downloads folder with full permissions
RUN mkdir -p /app/downloads && chmod 777 /app/downloads

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY templates/ ./templates/

# Railway uses dynamic PORT - must use environment variable
# Default to 8080 if PORT not set
ENV PORT=8080

# Expose port (informational only)
EXPOSE $PORT

# Start command - use shell form to expand $PORT variable
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 300
