FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir aiohttp aiohttp-sse-client

# Copy the relay server code
COPY audio-relay-server.py .

EXPOSE 8001

CMD ["python", "audio-relay-server.py"]