FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt aiohttp>=3.9.0 python-dotenv

# Copy backend code
COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY .env.local /app/.env.local

# Set Python path so aspects can be imported
ENV PYTHONPATH=/app/backend
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "/app/scripts/local-server.py"]
