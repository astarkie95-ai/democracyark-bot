FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "bot.py"]
# Railway Dockerfile for Dododex headless fetch (Playwright)
# If you don't want Dododex scraping, you can omit this file and ignore USE_DODODEX.
FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app

# Copy project
COPY . /app

# Install python deps if requirements.txt exists
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Ensure playwright browsers are present (already included in base image, but keep safe)
RUN python -m playwright install chromium

CMD ["python", "bot.py"]
