import sys
import struct
import json
import subprocess
import os
import socket
import logging

# Configure logging
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bridge.log')
logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s %(message)s')

IPC_PORT = 19375 # Shared port with GUI application

def get_message():
    text_length_bytes = sys.stdin.buffer.read(4)
    if not text_length_bytes or len(text_length_bytes) < 4:
        return None
    text_length = struct.unpack('i', text_length_bytes)[0]
    text = sys.stdin.buffer.read(text_length).decode('utf-8')
    return json.loads(text)

def send_message(message):
    msg_json = json.dumps(message)
    msg_bytes = msg_json.encode('utf-8')
    sys.stdout.buffer.write(struct.pack('i', len(msg_bytes)))
    sys.stdout.buffer.write(msg_bytes)
    sys.stdout.buffer.flush()

def main():
    if sys.platform == "win32":
        # Force binary mode on Windows for native messaging
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    logging.info("Bridge started")
    try:
        while True:
            message = get_message()
            if message is not None:
                logging.info(f"Received message: {message}")
                url = message.get('url')
                if url:
                    # Try to send via IPC first
                    ipc_success = False
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.connect(('127.0.0.1', IPC_PORT))
                        s.sendall((json.dumps(message) + '\n').encode('utf-8'))
                        s.close()
                        ipc_success = True
                        logging.info("Sent URL via IPC")
                    except Exception as e:
                        logging.warning(f"IPC connection failed, app likely not running: {e}")

                    if not ipc_success:
                        # Fallback: Launch the app
                        current_dir = os.path.dirname(os.path.abspath(__file__))
                        # Ensure we maintain backward compatibility with titan_app.py
                        app_path = os.path.abspath(os.path.join(current_dir, '..', 'titan_app.py'))
                        
                        cmd = [sys.executable, app_path, url]
                        
                        kwargs = {}
                        if sys.platform == 'win32':
                            kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                        else:
                            kwargs['start_new_session'] = True
                            
                        logging.info(f"Launching app: {cmd}")
                        subprocess.Popen(cmd, cwd=os.path.dirname(app_path), **kwargs)
                        
                    # Respond to Chrome
                    send_message({"status": "received", "url": url})
            else:
                break
    except Exception as e:
        logging.error(f"Error in bridge: {e}")

if __name__ == '__main__':
    main()
