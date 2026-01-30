# Merged Dockerfile (existing Railway build + Playwright/Chromium support for Dododex headless fetch)
# Uses Playwright base image so Chromium + system deps are included.
FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Ensure Chromium is available (base image usually includes it; this keeps it explicit)
RUN python -m playwright install chromium

CMD ["python", "bot.py"]
