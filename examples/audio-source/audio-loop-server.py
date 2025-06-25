#!/usr/bin/env python3
"""
Stateful audio loop server that continuously plays audio regardless of listeners.
Provides HTTP streaming API for clients to connect at any point.
"""

import asyncio
import time
import wave
import struct
import uuid
import logging
import os
from aiohttp import web
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioLoopServer:
    def __init__(self, wav_file="/app/audio.wav", chunk_duration_ms=100):  # Increased chunk size
        self.wav_file = wav_file
        self.chunk_duration_ms = chunk_duration_ms
        self.audio_chunks = []
        self.current_position = 0
        self.loop_start_time = None
        self.interval_id = None
        self.loop_count = 0
        self.listeners = set()
        self.sample_rate = 44100  # Default, will be overridden
        self.channels = 1
        self.sample_width = 2
        
    def load_audio(self):
        """Load and chunk the audio file"""
        try:
            with wave.open(self.wav_file, 'rb') as wav:
                self.params = wav.getparams()
                self.sample_rate = self.params.framerate
                self.channels = self.params.nchannels
                self.sample_width = self.params.sampwidth
                audio_data = wav.readframes(self.params.nframes)
                
            # Calculate chunk size based on duration
            bytes_per_ms = (self.sample_rate * self.sample_width * self.channels) // 1000
            chunk_size = bytes_per_ms * self.chunk_duration_ms
            
            # Ensure chunk size is even for 16-bit audio
            if chunk_size % 2 != 0:
                chunk_size += 1
                
            # Split audio into chunks
            self.audio_chunks = []
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                if len(chunk) == chunk_size:  # Only add full-sized chunks
                    self.audio_chunks.append(chunk)
                elif chunk:  # Pad the last chunk if needed
                    padded = chunk + b'\x00' * (chunk_size - len(chunk))
                    self.audio_chunks.append(padded)
                    
            self.total_duration_ms = len(self.audio_chunks) * self.chunk_duration_ms
            
            logger.info(f"Loaded audio: {self.channels} channels, "
                       f"{self.sample_rate} Hz, {self.sample_width * 8}-bit, "
                       f"{len(self.audio_chunks)} chunks, {self.total_duration_ms}ms total")
                       
        except Exception as e:
            logger.error(f"Failed to load audio: {e}")
            raise
    
    async def audio_loop(self):
        """Main audio playback loop - runs continuously"""
        await asyncio.sleep(1)  # Give server time to start
        
        while True:
            # Start of new loop
            if self.current_position == 0:
                self.interval_id = str(uuid.uuid4())
                self.loop_start_time = time.time()
                self.loop_count += 1
                logger.info(f"Starting loop #{self.loop_count}, interval: {self.interval_id}")
            
            # Current chunk data
            chunk_data = {
                'interval_id': self.interval_id,
                'loop_count': self.loop_count,
                'position': self.current_position,
                'total_chunks': len(self.audio_chunks),
                'timestamp': int(time.time() * 1000),
                'audio': self.audio_chunks[self.current_position],
                'sample_rate': self.sample_rate,
                'channels': self.channels,
                'sample_width': self.sample_width
            }
            
            # Send to all active listeners
            disconnected = set()
            for listener in self.listeners:
                try:
                    await listener(chunk_data)
                except Exception as e:
                    logger.debug(f"Listener error: {e}")
                    disconnected.add(listener)
            
            self.listeners -= disconnected
            
            # Move to next position
            self.current_position = (self.current_position + 1) % len(self.audio_chunks)
            
            # Sleep for chunk duration
            await asyncio.sleep(self.chunk_duration_ms / 1000.0)
    
    def get_current_state(self):
        """Get current playback state"""
        elapsed_ms = 0
        if self.loop_start_time:
            elapsed_ms = int((time.time() - self.loop_start_time) * 1000)
            
        return {
            'interval_id': self.interval_id,
            'loop_count': self.loop_count,
            'current_position': self.current_position,
            'total_chunks': len(self.audio_chunks),
            'elapsed_ms': elapsed_ms,
            'total_duration_ms': self.total_duration_ms,
            'chunk_duration_ms': self.chunk_duration_ms,
            'audio_format': {
                'channels': self.channels,
                'sample_rate': self.sample_rate,
                'bits_per_sample': self.sample_width * 8
            }
        }

# Global server instance
audio_server = AudioLoopServer()

async def handle_index(request):
    """Serve simple web player"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Audio Loop Broadcast</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            button { padding: 12px 24px; font-size: 16px; margin: 10px; border: none; border-radius: 5px; cursor: pointer; }
            button:hover { opacity: 0.9; }
            .play { background: #4CAF50; color: white; }
            .stop { background: #f44336; color: white; }
            #status { margin: 20px 0; padding: 15px; background: #f0f0f0; border-radius: 5px; }
            .metric { margin: 8px 0; display: flex; justify-content: space-between; }
            .metric span { font-weight: bold; }
            #error { color: red; margin: 10px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎵 Audio Loop Broadcast</h1>
            <p>This server continuously broadcasts audio in a loop. Connect anytime to join the stream!</p>
            <div>
                <button class="play" onclick="startStream()">▶️ Play Stream</button>
                <button class="stop" onclick="stopStream()">⏹️ Stop</button>
            </div>
            <div id="error"></div>
            <div id="status">
                <div class="metric">Status: <span id="state">Disconnected</span></div>
                <div class="metric">Loop Count: <span id="loop">-</span></div>
                <div class="metric">Position: <span id="position">-</span></div>
                <div class="metric">Interval ID: <span id="interval">-</span></div>
                <div class="metric">Audio Format: <span id="format">-</span></div>
            </div>
        </div>
        
        <script>
            let eventSource = null;
            let audioContext = null;
            let nextPlayTime = 0;
            let audioFormat = null;
            let isPlaying = false;
            
            async function startStream() {
                if (eventSource) return;
                
                try {
                    // Initialize audio context
                    audioContext = new (window.AudioContext || window.webkitAudioContext)();
                    nextPlayTime = audioContext.currentTime + 0.1; // Small buffer
                    isPlaying = true;
                    
                    // Connect to SSE stream
                    eventSource = new EventSource('/stream');
                    document.getElementById('state').textContent = 'Connecting...';
                    document.getElementById('error').textContent = '';
                    
                    eventSource.onmessage = (event) => {
                        const data = JSON.parse(event.data);
                        
                        // Update audio format on first message
                        if (!audioFormat && data.audio_format) {
                            audioFormat = data.audio_format;
                            document.getElementById('format').textContent = 
                                `${audioFormat.sample_rate}Hz, ${audioFormat.bits_per_sample}-bit, ${audioFormat.channels}ch`;
                        }
                        
                        // Update UI
                        document.getElementById('state').textContent = 'Connected';
                        document.getElementById('loop').textContent = data.loop_count;
                        document.getElementById('position').textContent = 
                            `${data.position}/${data.total_chunks}`;
                        document.getElementById('interval').textContent = 
                            data.interval_id ? data.interval_id.substring(0, 8) + '...' : '-';
                        
                        // Play audio chunk
                        if (data.audio && isPlaying) {
                            playChunk(data);
                        }
                    };
                    
                    eventSource.onerror = (e) => {
                        document.getElementById('state').textContent = 'Error';
                        document.getElementById('error').textContent = 'Connection lost. Click Play to reconnect.';
                        stopStream();
                    };
                } catch (e) {
                    document.getElementById('error').textContent = 'Error: ' + e.message;
                    stopStream();
                }
            }
            
            function playChunk(data) {
                try {
                    // Convert hex to bytes
                    const bytes = new Uint8Array(data.audio.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                    
                    // Use the actual audio format from server
                    const sampleRate = data.sample_rate || 44100;
                    const channels = data.channels || 1;
                    const sampleWidth = data.sample_width || 2;
                    
                    // Calculate samples based on actual format
                    const samplesPerChannel = bytes.length / (channels * sampleWidth);
                    
                    // Create audio buffer with correct parameters
                    const buffer = audioContext.createBuffer(
                        channels, 
                        samplesPerChannel, 
                        sampleRate
                    );
                    
                    // Convert bytes to float samples based on bit depth
                    if (sampleWidth === 2) {  // 16-bit
                        for (let channel = 0; channel < channels; channel++) {
                            const channelData = buffer.getChannelData(channel);
                            for (let i = 0; i < samplesPerChannel; i++) {
                                const byteIndex = (i * channels + channel) * 2;
                                const int16 = (bytes[byteIndex + 1] << 8) | bytes[byteIndex];
                                channelData[i] = (int16 > 32767 ? int16 - 65536 : int16) / 32768.0;
                            }
                        }
                    } else if (sampleWidth === 1) {  // 8-bit
                        for (let channel = 0; channel < channels; channel++) {
                            const channelData = buffer.getChannelData(channel);
                            for (let i = 0; i < samplesPerChannel; i++) {
                                const byteIndex = i * channels + channel;
                                channelData[i] = (bytes[byteIndex] - 128) / 128.0;
                            }
                        }
                    }
                    
                    // Create and play buffer source
                    const source = audioContext.createBufferSource();
                    source.buffer = buffer;
                    source.connect(audioContext.destination);
                    
                    // Schedule playback with proper timing
                    const now = audioContext.currentTime;
                    if (nextPlayTime < now) {
                        nextPlayTime = now + 0.01;  // Small buffer to avoid clicks
                    }
                    source.start(nextPlayTime);
                    nextPlayTime += buffer.duration;
                    
                } catch (e) {
                    console.error('Playback error:', e);
                    document.getElementById('error').textContent = 'Playback error: ' + e.message;
                }
            }
            
            function stopStream() {
                isPlaying = false;
                if (eventSource) {
                    eventSource.close();
                    eventSource = null;
                }
                if (audioContext) {
                    audioContext.close();
                    audioContext = null;
                }
                document.getElementById('state').textContent = 'Disconnected';
                audioFormat = null;
            }
        </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def handle_stream(request):
    """Server-Sent Events endpoint for audio streaming"""
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Access-Control-Allow-Origin'] = '*'
    
    await response.prepare(request)
    
    # Queue for this listener
    queue = asyncio.Queue(maxsize=5)  # Smaller queue to reduce latency
    
    async def listener(chunk_data):
        # Don't block if queue is full (drop old chunks)
        try:
            queue.put_nowait(chunk_data)
        except asyncio.QueueFull:
            queue.get_nowait()  # Remove oldest
            queue.put_nowait(chunk_data)
    
    # Register listener
    audio_server.listeners.add(listener)
    logger.info(f"Client connected. Total listeners: {len(audio_server.listeners)}")
    
    try:
        # Send initial state with audio format
        state = audio_server.get_current_state()
        await response.write(f"data: {json.dumps(state)}\n\n".encode())
        
        # Stream chunks
        while True:
            chunk_data = await queue.get()
            
            # Convert audio to hex for JSON, include format info
            message = {
                'interval_id': chunk_data['interval_id'],
                'loop_count': chunk_data['loop_count'],
                'position': chunk_data['position'],
                'total_chunks': chunk_data['total_chunks'],
                'timestamp': chunk_data['timestamp'],
                'audio': chunk_data['audio'].hex(),
                'sample_rate': chunk_data['sample_rate'],
                'channels': chunk_data['channels'],
                'sample_width': chunk_data['sample_width'],
                'audio_format': {
                    'channels': chunk_data['channels'],
                    'sample_rate': chunk_data['sample_rate'],
                    'bits_per_sample': chunk_data['sample_width'] * 8
                }
            }
            
            await response.write(f"data: {json.dumps(message)}\n\n".encode())
            
    except Exception as e:
        logger.error(f"Stream error: {e}")
    finally:
        audio_server.listeners.remove(listener)
        logger.info(f"Client disconnected. Total listeners: {len(audio_server.listeners)}")
    
    return response

async def handle_status(request):
    """JSON endpoint for current status"""
    state = audio_server.get_current_state()
    state['listeners'] = len(audio_server.listeners)
    return web.json_response(state)

async def start_background_tasks(app):
    """Start the audio loop"""
    audio_server.load_audio()
    app['audio_loop'] = asyncio.create_task(audio_server.audio_loop())

async def cleanup_background_tasks(app):
    """Cleanup on shutdown"""
    app['audio_loop'].cancel()
    await app['audio_loop']

def create_app():
    """Create the web application"""
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/stream', handle_stream)
    app.router.add_get('/status', handle_status)
    
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    return app

if __name__ == '__main__':
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=8000)