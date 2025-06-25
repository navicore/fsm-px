FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir aiohttp

# Copy the server code
COPY audio-loop-server.py .

# Copy the voice audio file
COPY final_notice.wav audio.wav

EXPOSE 8000

CMD ["python", "audio-loop-server.py"]