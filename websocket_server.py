import asyncio
import websockets
import serial
import serial.tools.list_ports
import signal
import sys
import os

# --- Configuration ---
SERIAL_BAUD_RATE = 9600
SERIAL_PORT = os.environ.get('SERIAL_PORT', 'COM15') # Use environment variable

# --- Global State ---
clients = set()
serial_conn = None

async def serial_reader(serial_port_name):
    """
    Reads structured data from Arduino and broadcasts to WebSocket clients
    """
    global serial_conn
    
    print(f"🔄 Attempting to connect to serial port: {serial_port_name}...")
    
    try:
        serial_conn = serial.Serial(serial_port_name, SERIAL_BAUD_RATE, timeout=0.1)
        await asyncio.sleep(2) 
        serial_conn.flushInput()
        
        print(f"✅ Serial connected on {serial_port_name}! Listening for LIVE_DATA.")

        while True:
            if serial_conn.in_waiting > 0:
                line = serial_conn.readline().decode('utf-8', 'ignore').strip()
                
                prefix = "LIVE_DATA: "
                if line.startswith(prefix):
                    data_to_broadcast = line[len(prefix):].strip() 
                    
                    if data_to_broadcast:
                        print(f"📊 Broadcasting: {data_to_broadcast}")
                        asyncio.create_task(broadcast(data_to_broadcast)) 
                        
            await asyncio.sleep(0.01)

    except serial.SerialException as e:
        print(f"❌ Serial Port Error: {e}")
        print(" Check if another program (like Arduino Serial Monitor) is using the port.")
    except Exception as e:
        print(f"⚠️ An unexpected error occurred in serial reader: {e}")
    finally:
        if serial_conn and serial_conn.is_open:
            serial_conn.close()


async def broadcast(message):
    """Sends a message to all connected WebSocket clients"""
    if not clients: 
        print("ℹ️ No clients connected to broadcast to")
        return
    
    tasks = []
    disconnected_clients = []
    
    for client in clients:
        tasks.append(client.send(message))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for client, result in zip(clients, results):
        if isinstance(result, Exception):
            print(f"❌ Client disconnected: {result}")
            disconnected_clients.append(client)
    
    for dc in disconnected_clients:
        clients.discard(dc)


async def websocket_handler(websocket, path=None):
    """Handles WebSocket client connections with remote support"""
    # Get client information
    client_ip = websocket.remote_address[0] if websocket.remote_address else "Unknown"
    print(f"🔗 New WebSocket connection from: {client_ip}")
    
    clients.add(websocket)
    
    try:
        # Send welcome message
        await websocket.send("CONNECTED:Local WebSocket Server Ready")
        
        # Keep connection alive and listen for messages
        async for message in websocket:
            print(f"📨 Received from client: {message}")
            # You can process incoming messages here if needed
            
    except websockets.exceptions.ConnectionClosed:
        print(f"❌ Connection closed by {client_ip}")
    except Exception as e:
        print(f"⚠️ WebSocket error with {client_ip}: {e}")
    finally:
        clients.discard(websocket)
        print(f"🔒 Client {client_ip} disconnected. Total clients: {len(clients)}")


async def main():
    print("🚀 Starting Local WebSocket Server with Remote Access...")
    print("📍 This server will accept connections from your cloud Flask app")
    
    # List available serial ports
    ports = serial.tools.list_ports.comports()
    print("🔍 Available serial ports:")
    for port in ports:
        print(f" - {port.device}: {port.description}")
    
    if not ports:
        print("❌ No serial ports found. Arduino communication disabled.")
    
    # Start serial reader if port is available
    serial_task = None
    try:
        serial_task = asyncio.create_task(serial_reader(SERIAL_PORT))
        print(f"✅ Serial reader started on {SERIAL_PORT}")
    except Exception as e:
        print(f"❌ Failed to start serial reader: {e}")
    
    # Start WebSocket server - CRITICAL: Listen on all interfaces (0.0.0.0)
    websocket_server = await websockets.serve(
        websocket_handler, 
        "0.0.0.0", # This allows remote connections
        8765
    )
    
    print(f"✅ WebSocket Server running on: ws://0.0.0.0:8765")
    print("🌐 Remote connections are ENABLED")
    print("💡 Make sure to configure port forwarding on your router!")
    
    # Wait for both tasks
    tasks = [websocket_server.wait_closed()]
    if serial_task:
        tasks.append(serial_task)
    
    await asyncio.gather(*tasks)


def signal_handler(sig, frame):
    print('\n🛑 Server stopped manually')
    if serial_conn and serial_conn.is_open:
        serial_conn.close()
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")