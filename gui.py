import tkinter as tk
from tkinter import ttk
import threading
import logging
import time
import queue

from config import MOVE_DELAY_MIN, MOVE_DELAY_MAX, WINDOW_WIDTH, WINDOW_HEIGHT, DEFAULT_INFINITE_WAIT, ENGINE_MAX_DEPTH, ENGINE_TIME_LIMIT


class BotState:
    def __init__(self):
        self.running = False
        self.stop_requested = False
        self.game_count = 0
        self.status = "Idle"
        self.log_queue = queue.Queue()
        self.infinite_wait = DEFAULT_INFINITE_WAIT
        self.move_delay_min = MOVE_DELAY_MIN
        self.move_delay_max = MOVE_DELAY_MAX
        self.max_depth = ENGINE_MAX_DEPTH
        self.time_limit = ENGINE_TIME_LIMIT

    def should_stop(self):
        return self.stop_requested

    def get_infinite_wait(self):
        return self.infinite_wait

    def get_move_delay_range(self):
        return (self.move_delay_min, self.move_delay_max)

    def get_max_depth(self):
        return self.max_depth

    def get_time_limit(self):
        return self.time_limit

    def request_stop(self):
        self.stop_requested = True

    def reset_stop(self):
        self.stop_requested = False


class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))


class ChessBotGUI:
    def __init__(self):
        self.state = BotState()
        self.game_thread = None
        self.root = None

    def run(self):
        self.root = tk.Tk()
        self.root.title("Chess Bot")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(350, 400)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._setup_logging()
        self._poll_log_queue()

        self.root.mainloop()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame, text="♟ Chess Bot Controller", font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 10))

        wait_frame = ttk.LabelFrame(
            main_frame, text="Wait Settings", padding=8)
        wait_frame.pack(fill=tk.X, pady=(0, 8))

        self.infinite_wait_var = tk.BooleanVar(value=DEFAULT_INFINITE_WAIT)
        self.state.infinite_wait = DEFAULT_INFINITE_WAIT
        self.infinite_wait_check = ttk.Checkbutton(
            wait_frame, text="Infinite wait for board detection",
            variable=self.infinite_wait_var, command=self._on_infinite_wait_change
        )
        self.infinite_wait_check.pack(anchor=tk.W)

        if DEFAULT_INFINITE_WAIT:
            self.wait_info_var = tk.StringVar(value="Mode: Infinite wait")
        else:
            self.wait_info_var = tk.StringVar(
                value="Default: 2 minutes timeout")
        self.wait_info_label = ttk.Label(
            wait_frame, textvariable=self.wait_info_var, font=("Segoe UI", 9))
        self.wait_info_label.pack(anchor=tk.W, pady=(4, 0))

        delay_frame = ttk.LabelFrame(
            main_frame, text="Move Delay (seconds)", padding=8)
        delay_frame.pack(fill=tk.X, pady=(0, 8))

        delay_input_frame = ttk.Frame(delay_frame)
        delay_input_frame.pack(fill=tk.X)

        ttk.Label(delay_input_frame, text="Min:",
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.delay_min_var = tk.DoubleVar(value=MOVE_DELAY_MIN)
        self.delay_min_entry = ttk.Entry(
            delay_input_frame, textvariable=self.delay_min_var, width=6, justify=tk.CENTER)
        self.delay_min_entry.pack(side=tk.LEFT, padx=(4, 12))
        self.delay_min_entry.bind("<FocusOut>", self._on_delay_min_focusout)
        self.delay_min_entry.bind("<Return>", self._on_delay_min_focusout)

        ttk.Label(delay_input_frame, text="Max:",
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.delay_max_var = tk.DoubleVar(value=MOVE_DELAY_MAX)
        self.delay_max_entry = ttk.Entry(
            delay_input_frame, textvariable=self.delay_max_var, width=6, justify=tk.CENTER)
        self.delay_max_entry.pack(side=tk.LEFT, padx=(4, 0))
        self.delay_max_entry.bind("<FocusOut>", self._on_delay_max_focusout)
        self.delay_max_entry.bind("<Return>", self._on_delay_max_focusout)

        engine_frame = ttk.LabelFrame(
            main_frame, text="Engine Settings", padding=8)
        engine_frame.pack(fill=tk.X, pady=(0, 8))

        engine_input_frame = ttk.Frame(engine_frame)
        engine_input_frame.pack(fill=tk.X)

        ttk.Label(engine_input_frame, text="Depth:",
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.depth_var = tk.IntVar(value=ENGINE_MAX_DEPTH)
        self.depth_spin = ttk.Spinbox(
            engine_input_frame, from_=1, to=20, textvariable=self.depth_var, width=5, justify=tk.CENTER)
        self.depth_spin.pack(side=tk.LEFT, padx=(4, 16))
        self.depth_spin.bind("<FocusOut>", self._on_depth_change)
        self.depth_spin.bind("<Return>", self._on_depth_change)

        ttk.Label(engine_input_frame, text="Time (s):",
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.time_var = tk.DoubleVar(value=ENGINE_TIME_LIMIT)
        self.time_entry = ttk.Entry(
            engine_input_frame, textvariable=self.time_var, width=6, justify=tk.CENTER)
        self.time_entry.pack(side=tk.LEFT, padx=(4, 0))
        self.time_entry.bind("<FocusOut>", self._on_time_change)
        self.time_entry.bind("<Return>", self._on_time_change)

        ctrl_frame = ttk.Frame(main_frame)
        ctrl_frame.pack(fill=tk.X, pady=(0, 8))

        self.start_btn = ttk.Button(
            ctrl_frame, text="▶ Start", command=self._on_start)
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.stop_btn = ttk.Button(
            ctrl_frame, text="■ Stop", command=self._on_stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        status_frame = ttk.LabelFrame(main_frame, text="Status", padding=6)
        status_frame.pack(fill=tk.X, pady=(0, 8))

        self.status_var = tk.StringVar(value="Idle")
        self.status_label = ttk.Label(
            status_frame, textvariable=self.status_var, font=("Segoe UI", 10))
        self.status_label.pack(fill=tk.X)

        self.game_count_var = tk.StringVar(value="Games played: 0")
        self.game_count_label = ttk.Label(
            status_frame, textvariable=self.game_count_var, font=("Segoe UI", 9))
        self.game_count_label.pack(fill=tk.X)

        log_frame = ttk.LabelFrame(main_frame, text="Log", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=10, width=38, font=(
            "Consolas", 8), state=tk.DISABLED, wrap=tk.WORD)
        log_scrollbar = ttk.Scrollbar(
            log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _setup_logging(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        queue_handler = QueueHandler(self.state.log_queue)
        queue_handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"))
        root_logger.addHandler(queue_handler)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.state.log_queue.get_nowait()
                self.log_text.configure(state=tk.NORMAL)
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log_queue)

    def _on_infinite_wait_change(self):
        self.state.infinite_wait = self.infinite_wait_var.get()
        if self.state.infinite_wait:
            self.wait_info_var.set("Mode: Infinite wait")
        else:
            self.wait_info_var.set("Default: 2 minutes timeout")

    def _on_delay_min_focusout(self, event=None):
        try:
            min_val = float(self.delay_min_var.get())
        except ValueError:
            min_val = MOVE_DELAY_MIN
            self.delay_min_var.set(min_val)
        max_val = float(self.delay_max_var.get())
        if min_val > max_val:
            min_val = max_val
            self.delay_min_var.set(f"{min_val:.2f}")
        if min_val < 0:
            min_val = 0
            self.delay_min_var.set(min_val)
        self.state.move_delay_min = min_val

    def _on_delay_max_focusout(self, event=None):
        try:
            max_val = float(self.delay_max_var.get())
        except ValueError:
            max_val = MOVE_DELAY_MAX
            self.delay_max_var.set(max_val)
        min_val = float(self.delay_min_var.get())
        if max_val < min_val:
            max_val = min_val
            self.delay_max_var.set(f"{max_val:.2f}")
        if max_val < 0:
            max_val = 0
            self.delay_max_var.set(max_val)
        self.state.move_delay_max = max_val

    def _on_depth_change(self, event=None):
        try:
            depth = int(self.depth_var.get())
        except ValueError:
            depth = ENGINE_MAX_DEPTH
            self.depth_var.set(depth)
        if depth < 1:
            depth = 1
            self.depth_var.set(depth)
        if depth > 20:
            depth = 20
            self.depth_var.set(depth)
        self.state.max_depth = depth

    def _on_time_change(self, event=None):
        try:
            time_val = float(self.time_var.get())
        except ValueError:
            time_val = ENGINE_TIME_LIMIT
            self.time_var.set(time_val)
        if time_val < 0.1:
            time_val = 0.1
            self.time_var.set(time_val)
        if time_val > 60:
            time_val = 60
            self.time_var.set(time_val)
        self.state.time_limit = time_val

    def _on_start(self):
        if self.state.running:
            return
        self.state.running = True
        self.state.reset_stop()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.status_var.set("Running...")

        self.game_thread = threading.Thread(
            target=self._game_loop, daemon=True)
        self.game_thread.start()

    def _on_stop(self):
        if not self.state.running:
            return
        self.state.request_stop()
        self.status_var.set("Stopping...")
        self.stop_btn.configure(state=tk.DISABLED)

    def _on_close(self):
        if self.state.running:
            self.state.request_stop()
            time.sleep(0.5)
        self.root.destroy()

    def _game_loop(self):
        from game import play_game

        while not self.state.should_stop():
            self.state.game_count += 1
            game_num = self.state.game_count
            self.root.after(0, self._update_status,
                            f"Game {game_num} in progress...")
            try:
                play_game(
                    stop_callback=self.state.should_stop,
                    infinite_wait=self.state.get_infinite_wait(),
                    delay_callback=self.state.get_move_delay_range,
                    max_depth=self.state.get_max_depth(),
                    time_limit=self.state.get_time_limit()
                )
            except Exception as e:
                logging.error(f"Error during game {game_num}: {e}")
            self.root.after(0, self._update_game_count)
            if self.state.should_stop():
                break
            self.root.after(0, self._update_status, "Waiting for next game...")
            time.sleep(2)

        self.state.running = False
        self.root.after(0, self._on_stopped)

    def _on_stopped(self):
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.status_var.set("Stopped")

    def _update_status(self, text):
        self.status_var.set(text)

    def _update_game_count(self):
        self.game_count_var.set(f"Games played: {self.state.game_count}")
