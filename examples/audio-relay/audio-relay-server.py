#!/usr/bin/env python3
"""
Audio relay server with variable latency buffer.
Buffers audio chunks and plays them back with user-configurable delay.
"""

import asyncio
import json
import logging
import os
import time
import collections
from aiohttp import web
from aiohttp_sse_client import client as sse_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioBuffer:
    """Ring buffer for audio chunks with timestamp tracking"""
    def __init__(self, max_seconds=20):
        self.max_size = max_seconds * 10  # Assuming 100ms chunks
        self.buffer = collections.deque(maxlen=self.max_size)
        self.start_time = None
        
    def add_chunk(self, chunk_data):
        """Add chunk with timing info"""
        if self.start_time is None:
            self.start_time = time.time()
            
        entry = {
            'data': chunk_data,
            'received_time': time.time(),
            'relative_time': time.time() - self.start_time
        }
        self.buffer.append(entry)
        
    def get_chunk_at_delay(self, delay_seconds):
        """Get chunk that should play now given the delay"""
        if not self.buffer or self.start_time is None:
            return None
            
        # Special case: zero delay means play the most recent chunk
        if delay_seconds == 0:
            return self.buffer[-1]['data'] if self.buffer else None
            
        current_relative_time = time.time() - self.start_time
        target_time = current_relative_time - delay_seconds
        
        # Find the chunk closest to our target time
        for entry in self.buffer:
            if entry['relative_time'] >= target_time:
                return entry['data']
                
        return None
    
    def get_buffer_stats(self):
        """Get buffer statistics"""
        if not self.buffer:
            return {'size': 0, 'duration': 0}
            
        return {
            'size': len(self.buffer),
            'duration': self.buffer[-1]['relative_time'] - self.buffer[0]['relative_time'] if len(self.buffer) > 1 else 0,
            'oldest_age': time.time() - self.buffer[0]['received_time'] if self.buffer else 0
        }

class AudioRelay:
    def __init__(self):
        self.source_url = os.environ.get("AUDIO_SOURCE_URL", "http://audio-source:8000")
        self.buffer = AudioBuffer()
        self.listeners = {}  # client_id -> {queue, delay_ms}
        self.current_state = {}
        self.is_connected = False
        self.relay_id = "relay-buffered"
        self.playback_position = 0
        self.client_counter = 0
        self.latest_chunk = None  # For real-time (0 delay) playback
        
    async def connect_to_source(self):
        """Connect to audio source and buffer chunks"""
        while True:
            try:
                logger.info(f"Connecting to audio source at {self.source_url}/stream")
                
                async with sse_client.EventSource(
                    f"{self.source_url}/stream",
                    timeout=None
                ) as event_source:
                    self.is_connected = True
                    logger.info("Connected to audio source")
                    
                    async for event in event_source:
                        if event.data:
                            try:
                                data = json.loads(event.data)
                                
                                # Update current state
                                self.current_state = {
                                    'source_interval_id': data.get('interval_id'),
                                    'source_loop_count': data.get('loop_count'),
                                    'source_position': data.get('position'),
                                    'total_chunks': data.get('total_chunks'),
                                    'audio_format': data.get('audio_format')
                                }
                                
                                # Buffer the chunk
                                self.buffer.add_chunk(data)
                                
                                # Store latest chunk for real-time playback
                                self.latest_chunk = data
                                
                                # Send immediately to real-time clients
                                await self.send_to_realtime_clients(data)
                                
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse event data: {e}")
                                
            except Exception as e:
                self.is_connected = False
                logger.error(f"Connection to source failed: {e}")
                await asyncio.sleep(5)
    
    async def send_to_realtime_clients(self, chunk_data):
        """Send chunk immediately to real-time (0 delay) clients"""
        for client_id, client_info in list(self.listeners.items()):
            if client_info['delay_ms'] == 0:
                try:
                    relay_data = {
                        **chunk_data,
                        'relay_id': self.relay_id,
                        'relay_timestamp': int(time.time() * 1000),
                        'source_timestamp': chunk_data.get('timestamp'),
                        'configured_delay_ms': 0,
                        'actual_delay_ms': int(time.time() * 1000) - chunk_data.get('timestamp', 0),
                        'buffer_stats': self.buffer.get_buffer_stats()
                    }
                    await client_info['queue'].put(relay_data)
                except Exception as e:
                    logger.error(f"Error sending to real-time client {client_id}: {e}")
    
    async def playback_loop(self):
        """Send buffered audio to clients based on their delay settings"""
        while True:
            try:
                # For each client with delay > 0, send the appropriate chunk from buffer
                for client_id, client_info in list(self.listeners.items()):
                    if client_info['delay_ms'] > 0:  # Skip real-time clients
                        try:
                            delay_seconds = client_info['delay_ms'] / 1000.0
                            chunk_data = self.buffer.get_chunk_at_delay(delay_seconds)
                            
                            if chunk_data:
                                # Add relay metadata
                                relay_data = {
                                    **chunk_data,
                                    'relay_id': self.relay_id,
                                    'relay_timestamp': int(time.time() * 1000),
                                    'source_timestamp': chunk_data.get('timestamp'),
                                    'configured_delay_ms': client_info['delay_ms'],
                                    'actual_delay_ms': int(time.time() * 1000) - chunk_data.get('timestamp', 0),
                                    'buffer_stats': self.buffer.get_buffer_stats()
                                }
                                
                                await client_info['queue'].put(relay_data)
                                
                        except Exception as e:
                            logger.error(f"Error sending to client {client_id}: {e}")
                        
                # Run at same rate as chunks (100ms)
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Playback loop error: {e}")
                await asyncio.sleep(0.1)

# Global relay instance
relay = AudioRelay()

async def handle_index(request):
    """Serve relay web interface with delay slider"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Audio Relay with Buffer</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            .container {{ max-width: 700px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #333; }}
            .controls {{ background: #e3f2fd; padding: 20px; border-radius: 5px; margin: 20px 0; }}
            .slider-container {{ margin: 20px 0; }}
            .slider {{ width: 100%; height: 40px; -webkit-appearance: none; appearance: none; background: #ddd; outline: none; opacity: 0.7; transition: opacity 0.2s; border-radius: 5px; }}
            .slider:hover {{ opacity: 1; }}
            .slider::-webkit-slider-thumb {{ -webkit-appearance: none; appearance: none; width: 25px; height: 40px; background: #2196F3; cursor: pointer; border-radius: 5px; }}
            .slider::-moz-range-thumb {{ width: 25px; height: 40px; background: #2196F3; cursor: pointer; border-radius: 5px; }}
            .delay-display {{ font-size: 24px; font-weight: bold; color: #2196F3; text-align: center; margin: 10px 0; }}
            button {{ padding: 12px 24px; font-size: 16px; margin: 10px; border: none; border-radius: 5px; cursor: pointer; }}
            button:hover {{ opacity: 0.9; }}
            .play {{ background: #4CAF50; color: white; }}
            .stop {{ background: #f44336; color: white; }}
            #status {{ margin: 20px 0; padding: 15px; background: #f0f0f0; border-radius: 5px; }}
            .metric {{ margin: 8px 0; display: flex; justify-content: space-between; }}
            .metric span {{ font-weight: bold; }}
            .buffer-stats {{ background: #fff3cd; padding: 10px; border-radius: 5px; margin: 10px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔄 Audio Relay with Variable Buffer</h1>
            
            <div class="controls">
                <h3>Latency Control</h3>
                <div class="slider-container">
                    <input type="range" min="0" max="15000" value="2000" step="100" class="slider" id="latencySlider">
                    <div class="delay-display" id="delayDisplay">2.0 seconds</div>
                </div>
                <div style="display: flex; justify-content: space-between; color: #666;">
                    <span>0s</span>
                    <span>Real-time ← → Delayed</span>
                    <span>15s</span>
                </div>
            </div>
            
            <div>
                <button class="play" onclick="startStream()">▶️ Play Stream</button>
                <button class="stop" onclick="stopStream()">⏹️ Stop</button>
            </div>
            
            <div class="buffer-stats" id="bufferStats">
                <strong>Buffer:</strong> <span id="bufferInfo">Not connected</span>
            </div>
            
            <div id="status">
                <div class="metric">Status: <span id="state">Disconnected</span></div>
                <div class="metric">Source Connected: <span id="source-connected">{'Yes' if relay.is_connected else 'No'}</span></div>
                <div class="metric">Loop Count: <span id="loop">-</span></div>
                <div class="metric">Position: <span id="position">-</span></div>
                <div class="metric">Actual Latency: <span id="actualLatency">-</span></div>
            </div>
        </div>
        
        <script>
            let eventSource = null;
            let audioContext = null;
            let nextPlayTime = 0;
            let isPlaying = false;
            let currentDelay = 2000;
            
            // Update delay display
            const slider = document.getElementById('latencySlider');
            const delayDisplay = document.getElementById('delayDisplay');
            
            slider.oninput = function() {{
                currentDelay = parseInt(this.value);
                const seconds = (currentDelay / 1000).toFixed(1);
                delayDisplay.textContent = `${{seconds}} seconds`;
                
                // Update delay on server if connected
                if (eventSource && eventSource.readyState === EventSource.OPEN) {{
                    fetch('/set-delay', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ delay_ms: currentDelay }})
                    }});
                }}
            }}
            
            async function startStream() {{
                if (eventSource) return;
                
                try {{
                    // Initialize audio context
                    audioContext = new (window.AudioContext || window.webkitAudioContext)();
                    nextPlayTime = audioContext.currentTime + 0.1;
                    isPlaying = true;
                    
                    // Connect to relay stream with delay parameter
                    eventSource = new EventSource(`/stream?delay=${{currentDelay}}`);
                    document.getElementById('state').textContent = 'Connecting...';
                    
                    eventSource.onmessage = (event) => {{
                        const data = JSON.parse(event.data);
                        
                        // Update UI
                        document.getElementById('state').textContent = 'Connected';
                        document.getElementById('loop').textContent = data.loop_count || '-';
                        document.getElementById('position').textContent = 
                            data.position !== undefined ? `${{data.position}}/${{data.total_chunks}}` : '-';
                        
                        // Show actual latency
                        if (data.actual_delay_ms !== undefined) {{
                            const actualSeconds = (data.actual_delay_ms / 1000).toFixed(1);
                            document.getElementById('actualLatency').textContent = `${{actualSeconds}}s`;
                        }}
                        
                        // Update buffer stats
                        if (data.buffer_stats) {{
                            const stats = data.buffer_stats;
                            document.getElementById('bufferInfo').textContent = 
                                `${{stats.size}} chunks, ${{stats.duration.toFixed(1)}}s buffered`;
                        }}
                        
                        // Play audio chunk
                        if (data.audio && isPlaying) {{
                            playChunk(data);
                        }}
                    }};
                    
                    eventSource.onerror = () => {{
                        document.getElementById('state').textContent = 'Error';
                        stopStream();
                    }};
                }} catch (e) {{
                    console.error('Error:', e);
                    stopStream();
                }}
            }}
            
            function playChunk(data) {{
                try {{
                    const bytes = new Uint8Array(data.audio.match(/.{{1,2}}/g).map(byte => parseInt(byte, 16)));
                    const sampleRate = data.sample_rate || 44100;
                    const channels = data.channels || 1;
                    const sampleWidth = data.sample_width || 2;
                    const samplesPerChannel = bytes.length / (channels * sampleWidth);
                    
                    const buffer = audioContext.createBuffer(channels, samplesPerChannel, sampleRate);
                    
                    if (sampleWidth === 2) {{
                        for (let channel = 0; channel < channels; channel++) {{
                            const channelData = buffer.getChannelData(channel);
                            for (let i = 0; i < samplesPerChannel; i++) {{
                                const byteIndex = (i * channels + channel) * 2;
                                const int16 = (bytes[byteIndex + 1] << 8) | bytes[byteIndex];
                                channelData[i] = (int16 > 32767 ? int16 - 65536 : int16) / 32768.0;
                            }}
                        }}
                    }}
                    
                    const source = audioContext.createBufferSource();
                    source.buffer = buffer;
                    source.connect(audioContext.destination);
                    
                    const now = audioContext.currentTime;
                    if (nextPlayTime < now) {{
                        nextPlayTime = now + 0.01;
                    }}
                    source.start(nextPlayTime);
                    nextPlayTime += buffer.duration;
                    
                }} catch (e) {{
                    console.error('Playback error:', e);
                }}
            }}
            
            function stopStream() {{
                isPlaying = false;
                if (eventSource) {{
                    eventSource.close();
                    eventSource = null;
                }}
                if (audioContext) {{
                    audioContext.close();
                    audioContext = null;
                }}
                document.getElementById('state').textContent = 'Disconnected';
                document.getElementById('bufferInfo').textContent = 'Not connected';
            }}
        </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def handle_stream(request):
    """SSE endpoint for relayed audio stream"""
    # Get requested delay from query params
    delay_ms = int(request.query.get('delay', '2000'))
    delay_ms = max(0, min(15000, delay_ms))  # Clamp to valid range
    
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    
    await response.prepare(request)
    
    # Create queue for this listener
    queue = asyncio.Queue(maxsize=10)
    client_id = relay.client_counter
    relay.client_counter += 1
    
    relay.listeners[client_id] = {
        'queue': queue,
        'delay_ms': delay_ms
    }
    
    logger.info(f"Client {client_id} connected with {delay_ms}ms delay. Total: {len(relay.listeners)}")
    
    try:
        while True:
            chunk_data = await queue.get()
            message = f"data: {json.dumps(chunk_data)}\n\n"
            await response.write(message.encode())
            
    except Exception as e:
        logger.error(f"Stream error: {e}")
    finally:
        del relay.listeners[client_id]
        logger.info(f"Client {client_id} disconnected. Total: {len(relay.listeners)}")
    
    return response

async def handle_set_delay(request):
    """Update delay for a client"""
    try:
        data = await request.json()
        delay_ms = int(data.get('delay_ms', 2000))
        delay_ms = max(0, min(15000, delay_ms))  # Clamp to valid range
        
        # Update delay for the most recent client (simplified for demo)
        if relay.listeners:
            client_id = max(relay.listeners.keys())
            relay.listeners[client_id]['delay_ms'] = delay_ms
            logger.info(f"Updated client {client_id} delay to {delay_ms}ms")
        
        return web.json_response({'status': 'ok', 'delay_ms': delay_ms})
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=400)

async def handle_status(request):
    """Status endpoint"""
    buffer_stats = relay.buffer.get_buffer_stats()
    status = {
        'relay_id': relay.relay_id,
        'source_url': relay.source_url,
        'is_connected': relay.is_connected,
        'listeners': len(relay.listeners),
        'buffer_stats': buffer_stats,
        'current_state': relay.current_state
    }
    return web.json_response(status)

async def start_background_tasks(app):
    """Start background tasks"""
    app['source_connection'] = asyncio.create_task(relay.connect_to_source())
    app['playback_loop'] = asyncio.create_task(relay.playback_loop())

async def cleanup_background_tasks(app):
    """Cleanup on shutdown"""
    app['source_connection'].cancel()
    app['playback_loop'].cancel()

def create_app():
    """Create the web application"""
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/stream', handle_stream)
    app.router.add_post('/set-delay', handle_set_delay)
    app.router.add_get('/status', handle_status)
    
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    return app

if __name__ == '__main__':
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=8001)