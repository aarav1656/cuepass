FROM python:3.12-slim

WORKDIR /app

# Install system deps for curl (archive.org fetch) and ffmpeg (not needed for subtitle-only,
# but included for completeness if audio QC is added later).
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

RUN mkdir -p data

ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
