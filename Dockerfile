FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

# Install deps (browsers pre-installed → no extra downloads)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Xvfb + minimal X deps (fixes dbus/X11 errors)
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libdbus-1-3 \
    libgbm1 \
    && rm -rf /var/lib/apt/lists/*

# Copy project
COPY . .

# Run with FULL xvfb-run (proper HD screen + security)
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24 -ac -nolisten tcp -dpi 96 +extension GLX +render", \
     "python", "grok_auto.py", "--upload-drive"]