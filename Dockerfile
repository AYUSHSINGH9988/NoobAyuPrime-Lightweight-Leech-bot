FROM python:3.11-slim

# Railway builds ke liye zaroori variable
ENV DEBIAN_FRONTEND=noninteractive

# Update aur install ko optimize karo
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    aria2 \
    curl \
    unzip \
    && curl -fsSL https://rclone.org/install.sh | bash \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
