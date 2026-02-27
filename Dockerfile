FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

# Install deps (browsers are ALREADY in the image → no download, no error)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Xvfb for virtual display in container
RUN apt-get update && apt-get install -y --no-install-recommends xvfb && rm -rf /var/lib/apt/lists/*

# Copy your entire project
COPY . .

# Run with xvfb-run for virtual display
CMD ["xvfb-run", "-a", "python", "grok_auto.py", "--upload-drive"]
