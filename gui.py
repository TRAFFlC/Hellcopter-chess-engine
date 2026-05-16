import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
import chess
import chess.pgn
import io

import engine_wrapper as ew

class EngineGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Hellcopter Chess Engine")
        self.root.geometry("800x600")
        
        self.board = chess.Board()
        self.move_history = []
        self.result_queue = queue.Queue()
        
        self.setup_ui()
        self.root.after(100, self.process_queue)
        
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(main_frame, padding="10")
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.board_text = tk.Text(left_frame, width=45, height=20, font=("Courier", 14))
        self.board_text.pack(fill=tk.BOTH, expand=True)
        
        self.history_text = scrolledtext.ScrolledText(left_frame, width=45, height=8, font=("Courier", 10))
        self.history_text.pack(fill=tk.X, pady=5)
        
        ttk.Label(right_frame, text="FEN:").pack(anchor=tk.W)
        self.fen_entry = ttk.Entry(right_frame, width=40)
        self.fen_entry.pack(fill=tk.X, pady=5)
        self.fen_entry.bind("<Return>", self.on_fen_enter)
        
        ttk.Label(right_frame, text="Search Time (s):").pack(anchor=tk.W)
        self.time_var = tk.StringVar(value="2.0")
        ttk.Entry(right_frame, textvariable=self.time_var, width=10).pack(anchor=tk.W, pady=5)
        
        ttk.Label(right_frame, text="Max Depth:").pack(anchor=tk.W)
        self.depth_var = tk.StringVar(value="100")
        ttk.Entry(right_frame, textvariable=self.depth_var, width=10).pack(anchor=tk.W, pady=5)
        
        ttk.Button(right_frame, text="Analyze", command=self.analyze).pack(fill=tk.X, pady=5)
        ttk.Button(right_frame, text="New Game", command=self.new_game).pack(fill=tk.X, pady=5)
        ttk.Button(right_frame, text="Undo", command=self.undo_move).pack(fill=tk.X, pady=5)
        
        ttk.Label(right_frame, text="Move:").pack(anchor=tk.W, pady=(10,0))
        self.move_entry = ttk.Entry(right_frame, width=10)
        self.move_entry.pack(anchor=tk.W)
        self.move_entry.bind("<Return>", self.make_move)
        ttk.Button(right_frame, text="Make Move", command=self.make_move).pack(fill=tk.X, pady=5)
        
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(right_frame, textvariable=self.status_var).pack(anchor=tk.W, pady=10)
        
        self.update_board()
        
    def update_board(self):
        board_str = str(self.board)
        self.board_text.delete(1.0, tk.END)
        self.board_text.insert(tk.END, board_str)
        self.fen_entry.delete(0, tk.END)
        self.fen_entry.insert(0, self.board.fen())
        
        self.history_text.delete(1.0, tk.END)
        if self.move_history:
            moves_str = " ".join(self.move_history)
            self.history_text.insert(tk.END, moves_str)
            
    def analyze(self):
        self.status_var.set("Searching...")
        fen = self.board.fen()
        time_limit = float(self.time_var.get())
        max_depth = int(self.depth_var.get())
        
        def search_thread():
            try:
                ew.reload_library()
                move, score, nodes = ew.search_with_score(fen, time_limit, max_depth)
                self.result_queue.put(("move", move, score, nodes))
            except Exception as e:
                self.result_queue.put(("error", str(e)))
                
        threading.Thread(target=search_thread, daemon=True).start()
        
    def process_queue(self):
        try:
            while True:
                result = self.result_queue.get_nowait()
                if result[0] == "move":
                    _, move, score, nodes = result
                    self.status_var.set(f"Move: {move}, Score: {score}, Nodes: {nodes:,}")
                    if self.board.is_legal(chess.Move.from_uci(move)):
                        self.board.push_uci(move)
                        self.move_history.append(move)
                        self.update_board()
                elif result[0] == "error":
                    self.status_var.set(f"Error: {result[1]}")
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)
        
    def new_game(self):
        self.board = chess.Board()
        self.move_history = []
        self.update_board()
        self.status_var.set("New game")
        
    def undo_move(self):
        if self.move_history:
            self.board.pop()
            self.move_history.pop()
            self.update_board()
            self.status_var.set("Move undone")
            
    def make_move(self, event=None):
        move_str = self.move_entry.get().strip()
        if not move_str:
            return
        try:
            move = self.board.parse_uci(move_str)
            self.board.push(move)
            self.move_history.append(move_str)
            self.update_board()
            self.move_entry.delete(0, tk.END)
            self.status_var.set(f"Played {move_str}")
        except ValueError:
            self.status_var.set("Invalid move")
            
    def on_fen_enter(self, event=None):
        fen = self.fen_entry.get().strip()
        try:
            self.board = chess.Board(fen)
            self.move_history = []
            self.update_board()
            self.status_var.set("Position loaded")
        except ValueError:
            self.status_var.set("Invalid FEN")
            
    def run(self):
        self.root.mainloop()

def main():
    ew.reload_library()
    app = EngineGUI()
    app.run()

if __name__ == "__main__":
    main()
