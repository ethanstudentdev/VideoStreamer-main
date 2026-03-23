import json
import socket
import threading
from pathlib import Path

HOST = '127.0.0.1'
PORT = 5000
BUFFER_SIZE = 64 * 1024
MEDIA_ROOT = Path('/media/rsbp5/media')
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mkv'}
CATEGORY_DIRS = {
    'movies': MEDIA_ROOT / 'movies',
    'shows': MEDIA_ROOT / 'shows',
}

def send_json(conn: socket.socket, payload: dict) -> None:
    message = json.dumps(payload) + '\n'
    conn.sendall(message.encode('utf-8'))


def read_json(conn_file) -> dict:
    line = conn_file.readline()
    if not line:
        raise ConnectionError('Client disconnected before sending a request.')
    return json.loads(line.decode('utf-8'))

def validate_category(category: str) -> Path:
    if category not in CATEGORY_DIRS:
        raise ValueError('Invalid category.')
    return CATEGORY_DIRS[category]

def list_media(category: str) -> list[str]:
    category_dir = validate_category(category)
    if not category_dir.exists():
        return []

    items = [
        path.relative_to(category_dir).as_posix()
        for path in category_dir.rglob('*')
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    items.sort()
    return items

def resolve_media_path(category: str, relative_name: str) -> Path:
    category_dir = validate_category(category).resolve()
    requested_path = (category_dir / relative_name).resolve()

    if category_dir != requested_path.parent and category_dir not in requested_path.parents:
        raise PermissionError('Requested path is outside the media folder.')
    if not requested_path.is_file():
        raise FileNotFoundError('Requested file does not exist.')
    if requested_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(f'Only these file types are allowed: {sorted(VIDEO_EXTENSIONS)}')

    return requested_path

def stream_media(conn: socket.socket, media_path: Path) -> int:
    bytes_sent = 0
    with media_path.open('rb') as media_file:
        while True:
            chunk = media_file.read(BUFFER_SIZE)
            if not chunk:
                break
            conn.sendall(chunk)
            bytes_sent += len(chunk)
    return bytes_sent

def handle_client(conn: socket.socket, address) -> None:
    print(f'[SERVER] Connection accepted from {address[0]}:{address[1]}')
    conn_file = conn.makefile('rb')

    try:
        request = read_json(conn_file)
        action = request.get('action')
        print(f'[SERVER] Request: {request}')

        if action == 'list':
            category = request.get('category', '')
            items = list_media(category)
            send_json(conn, {'status': 'ok', 'items': items, 'extensions': sorted(VIDEO_EXTENSIONS)})
            print(f'[SERVER] Sent {len(items)} item(s) for {category}.')

        elif action == 'play':
            category = request.get('category', '')
            name = request.get('name', '')
            media_path = resolve_media_path(category, name)
            file_size = media_path.stat().st_size

            send_json(
                conn,
                {
                    'status': 'ok',
                    'name': media_path.name,
                    'relative_name': name,
                    'size': file_size,
                    'suffix': media_path.suffix.lower(),
                    'buffer_size': BUFFER_SIZE,
                },
            )
            print(f'[SERVER] Streaming {name} ({file_size} bytes).')
            bytes_sent = stream_media(conn, media_path)
            print(f'[SERVER] Finished streaming {name} ({bytes_sent} bytes sent).')

        else:
            send_json(conn, {'status': 'error', 'message': 'Unknown action.'})
            print('[SERVER] Unknown action received.')

    except (BrokenPipeError, ConnectionResetError) as exc:
        print(f'[SERVER] Client disconnected during transfer: {exc}')
    except Exception as exc:
        try:
            send_json(conn, {'status': 'error', 'message': str(exc)})
        except OSError:
            pass
        print(f'[SERVER] Error: {exc}')
    finally:
        try:
            conn_file.close()
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass
        print('[SERVER] Connection closed.')

def main() -> None:
    for path in CATEGORY_DIRS.values():
        path.mkdir(parents=True, exist_ok=True)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(8)

    print(f'[SERVER] Listening on {HOST}:{PORT}')
    print(f'[SERVER] Media root: {MEDIA_ROOT}')
    print(f'[SERVER] Allowed types: {sorted(VIDEO_EXTENSIONS)}')
    print('[SERVER] Press Ctrl+C to stop.')

    try:
        while True:
            conn, address = server.accept()
            threading.Thread(target=handle_client, args=(conn, address), daemon=True).start()
    except KeyboardInterrupt:
        print('\n[SERVER] Shutting down.')
    finally:
        server.close()

if __name__ == '__main__':
    main()
