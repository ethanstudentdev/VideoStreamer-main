import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

HOST = '127.0.0.1'
PORT = 5000
BUFFER_SIZE = 64 * 1024
PIPE_DIR = Path(tempfile.gettempdir()) / 'media_client'


def send_json(sock: socket.socket, payload: dict) -> None:
    message = json.dumps(payload) + '\n'
    sock.sendall(message.encode('utf-8'))


def read_json(sock_file) -> dict:
    line = sock_file.readline()
    if not line:
        raise ConnectionError('Server closed the connection unexpectedly.')
    return json.loads(line.decode('utf-8'))


def request_media_list(category: str) -> list[str]:
    with socket.create_connection((HOST, PORT)) as sock:
        sock_file = sock.makefile('rb')
        send_json(sock, {'action': 'list', 'category': category})
        response = read_json(sock_file)

        if response.get('status') != 'ok':
            raise RuntimeError(response.get('message', 'Unknown server error.'))

        return response.get('items', [])


def create_named_pipe(suffix: str) -> Path:
    PIPE_DIR.mkdir(parents=True, exist_ok=True)
    safe_suffix = suffix if suffix.startswith('.') else '.bin'
    pipe_path = PIPE_DIR / f'stream_{uuid.uuid4().hex}{safe_suffix}'
    os.mkfifo(pipe_path)
    return pipe_path


def start_vlc_player(stream_path: Path):
    commands = [
        ['vlc', '--avcodec-hw=none', '--file-caching=300', '--network-caching=300', str(stream_path)],
        ['cvlc', '--avcodec-hw=none', '--file-caching=300', '--network-caching=300', str(stream_path)],
        ['mpv', '--cache=yes', '--demuxer-max-bytes=64M', str(stream_path)],
    ]

    for command in commands:
        try:
            return subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            continue

    raise FileNotFoundError('VLC or MPV was not found. Install VLC with: sudo apt install vlc')



def stream_media_to_player(category: str, relative_name: str, progress_callback=None, status_callback=None) -> None:
    pipe_path = None
    player_process = None

    try:
        with socket.create_connection((HOST, PORT)) as sock:
            sock_file = sock.makefile('rb')
            send_json(sock, {'action': 'play', 'category': category, 'name': relative_name})
            response = read_json(sock_file)

            if response.get('status') != 'ok':
                raise RuntimeError(response.get('message', 'Unknown server error.'))

            total_size = int(response.get('size', 0))
            suffix = response.get('suffix', Path(relative_name).suffix or '.bin')
            display_name = response.get('relative_name', relative_name)

            pipe_path = create_named_pipe(suffix)
            if status_callback is not None:
                status_callback(f'Launching player for {Path(display_name).name}...')

            player_process = start_vlc_player(pipe_path)

            bytes_streamed = 0
            chunk_counter = 0
            opened_pipe = False

            with pipe_path.open('wb') as pipe_file:
                opened_pipe = True
                if status_callback is not None:
                    status_callback(f'Streaming {Path(display_name).name}...')

                while bytes_streamed < total_size:
                    remaining = total_size - bytes_streamed
                    chunk = sock.recv(min(BUFFER_SIZE, remaining))
                    if not chunk:
                        raise ConnectionError('Connection closed before the stream finished.')
                    pipe_file.write(chunk)
                    bytes_streamed += len(chunk)
                    chunk_counter += 1

                    if chunk_counter % 8 == 0:
                        pipe_file.flush()

                    if progress_callback is not None:
                        progress_callback(bytes_streamed, total_size)

            if progress_callback is not None:
                progress_callback(total_size, total_size)
            if status_callback is not None:
                status_callback(f'Stream started: {Path(display_name).name}')

            if player_process is not None:
                threading.Thread(
                    target=wait_for_player_exit,
                    args=(player_process, pipe_path, opened_pipe),
                    daemon=True,
                ).start()
                pipe_path = None

    except BrokenPipeError:
        raise RuntimeError('The player closed before the stream finished.')
    finally:
        if pipe_path is not None and pipe_path.exists():
            try:
                pipe_path.unlink()
            except OSError:
                pass


def wait_for_player_exit(player_process, pipe_path: Path, _opened_pipe: bool) -> None:
    try:
        player_process.wait()
    finally:
        for _ in range(20):
            try:
                if pipe_path.exists():
                    pipe_path.unlink()
                break
            except OSError:
                time.sleep(0.25)


class MediaClientApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title('Media Client')
        self.root.geometry('760x520')
        self.root.minsize(680, 440)

        self.selected_category = None
        self.current_items: list[str] = []

        self.status_var = tk.StringVar(value='Ready. Select Movies or Shows.')
        self.progress_var = tk.DoubleVar(value=0.0)

        self.build_ui()

    def build_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill='both', expand=True)

        header = ttk.Label(main_frame, text='Media Client', font=('Arial', 18, 'bold'))
        header.pack(anchor='w', pady=(0, 10))

        button_row = ttk.Frame(main_frame)
        button_row.pack(fill='x', pady=(0, 10))

        self.movies_button = ttk.Button(button_row, text='Movies', command=lambda: self.load_category('movies'))
        self.movies_button.pack(side='left', padx=(0, 8))

        self.shows_button = ttk.Button(button_row, text='Shows', command=lambda: self.load_category('shows'))
        self.shows_button.pack(side='left')

        self.category_label = ttk.Label(main_frame, text='No category selected', font=('Arial', 12))
        self.category_label.pack(anchor='w', pady=(0, 8))

        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill='both', expand=True)

        self.media_listbox = tk.Listbox(list_frame, font=('Arial', 11))
        self.media_listbox.pack(side='left', fill='both', expand=True)
        self.media_listbox.bind('<Double-Button-1>', lambda _event: self.play_selected())

        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.media_listbox.yview)
        scrollbar.pack(side='right', fill='y')
        self.media_listbox.configure(yscrollcommand=scrollbar.set)

        controls = ttk.Frame(main_frame)
        controls.pack(fill='x', pady=(10, 0))

        self.refresh_button = ttk.Button(controls, text='Refresh List', command=self.refresh_category)
        self.refresh_button.pack(side='left', padx=(0, 8))

        self.play_button = ttk.Button(controls, text='Play Selected', command=self.play_selected)
        self.play_button.pack(side='left')

        self.progress = ttk.Progressbar(main_frame, mode='determinate', variable=self.progress_var, maximum=100)
        self.progress.pack(fill='x', pady=(12, 6))

        status_label = ttk.Label(main_frame, textvariable=self.status_var)
        status_label.pack(anchor='w')

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def set_busy(self, busy: bool) -> None:
        state = 'disabled' if busy else 'normal'
        for widget in (self.movies_button, self.shows_button, self.refresh_button, self.play_button):
            widget.config(state=state)

    def update_progress(self, current: int, total: int) -> None:
        percent = (current / total * 100.0) if total else 0.0
        self.root.after(0, lambda: self.progress_var.set(percent))
        self.root.after(0, lambda: self.set_status(f'Streaming... {percent:.1f}%'))

    def load_category(self, category: str) -> None:
        self.selected_category = category
        self.category_label.config(text=f'Category: {category.title()}')
        self.fetch_list_async(category)

    def refresh_category(self) -> None:
        if not self.selected_category:
            messagebox.showinfo('No Category', 'Select Movies or Shows first.')
            return
        self.fetch_list_async(self.selected_category)

    def fetch_list_async(self, category: str) -> None:
        self.set_busy(True)
        self.progress_var.set(0.0)
        self.set_status(f'Loading {category} from server...')

        def worker() -> None:
            try:
                items = request_media_list(category)
                self.root.after(0, lambda: self.populate_list(category, items))
            except Exception as exc:
                self.root.after(0, lambda: self.show_error(str(exc)))
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def populate_list(self, category: str, items: list[str]) -> None:
        self.current_items = items
        self.media_listbox.delete(0, tk.END)

        if not items:
            self.set_status(f'No supported video files found in {category}.')
            return

        for item in items:
            self.media_listbox.insert(tk.END, item)

        self.set_status(f'Loaded {len(items)} item(s) from {category}.')

    def play_selected(self) -> None:
        if not self.selected_category:
            messagebox.showinfo('No Category', 'Select Movies or Shows first.')
            return

        selection = self.media_listbox.curselection()
        if not selection:
            messagebox.showinfo('No Selection', 'Select a movie or show from the list first.')
            return

        selected_name = self.current_items[selection[0]]
        self.progress_var.set(0.0)
        self.set_busy(True)
        self.set_status(f'Connecting to server for {selected_name}...')

        def worker() -> None:
            try:
                stream_media_to_player(
                    self.selected_category,
                    selected_name,
                    progress_callback=self.update_progress,
                    status_callback=lambda message: self.root.after(0, lambda: self.set_status(message)),
                )
            except Exception as exc:
                self.root.after(0, lambda: self.show_error(str(exc)))
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def show_error(self, message: str) -> None:
        self.set_status(f'Error: {message}')
        messagebox.showerror('Client Error', message)


def main() -> None:
    PIPE_DIR.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    MediaClientApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
