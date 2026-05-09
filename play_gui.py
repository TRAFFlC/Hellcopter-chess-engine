import tkinter as tk
from tkinter import ttk, messagebox
import threading
import chess

from engine import ChessEngine

PIECE_SYMBOLS = {
    'P': '♙', 'N': '♘', 'B': '♗', 'R': '♖', 'Q': '♕', 'K': '♔',
    'p': '♟', 'n': '♞', 'b': '♝', 'r': '♜', 'q': '♛', 'k': '♚',
}

LIGHT_SQ = "#f0d9b5"
DARK_SQ = "#b58863"
HIGHLIGHT = "#f7ec4f"
SELECTED = "#779556"
MOVE_INDICATOR = "#aaffaa"


class ChessPlayGUI:
    def __init__(self, master=None):
        self.root = master or tk.Tk()
        self.root.title("Chess Engine Playground")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        self.board = chess.Board()
        self.engine = ChessEngine()
        self.engine.time_limit = 2.0
        self.max_depth = 6

        self.player_color = chess.WHITE
        self.flipped = False
        self.selected_square = None
        self.legal_targets = set()
        self.last_move = None
        self.engine_thinking = False
        self.game_over = False

        self._build_ui()
        self._draw_board()
        self._update_info()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(left_frame, width=520, height=520, bg="#333")
        self.canvas.pack(pady=(0, 10))
        self.canvas.bind("<Button-1>", self._on_click)

        control_frame = ttk.Frame(left_frame)
        control_frame.pack(fill=tk.X)

        ttk.Button(control_frame, text="New Game (White)",
                   command=lambda: self._new_game(chess.WHITE)).pack(side=tk.LEFT, padx=2)
        ttk.Button(control_frame, text="New Game (Black)",
                   command=lambda: self._new_game(chess.BLACK)).pack(side=tk.LEFT, padx=2)
        ttk.Button(control_frame, text="Flip Board",
                   command=self._flip_board).pack(side=tk.LEFT, padx=2)
        ttk.Button(control_frame, text="Undo",
                   command=self._undo).pack(side=tk.LEFT, padx=2)

        right_frame = ttk.Frame(main_frame, padding=(10, 0))
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)

        info_frame = ttk.LabelFrame(right_frame, text="Game Info", padding=8)
        info_frame.pack(fill=tk.X, pady=(0, 8))

        self.turn_var = tk.StringVar(value="White to move")
        ttk.Label(info_frame, textvariable=self.turn_var,
                  font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)

        self.status_var = tk.StringVar(value="Your turn")
        ttk.Label(info_frame, textvariable=self.status_var,
                  font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(4, 0))

        eval_frame = ttk.LabelFrame(right_frame, text="Engine", padding=8)
        eval_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(eval_frame, text="Depth:").grid(row=0, column=0, sticky=tk.W)
        self.depth_var = tk.IntVar(value=self.max_depth)
        depth_spin = ttk.Spinbox(eval_frame, from_=1, to=20,
                                 textvariable=self.depth_var, width=5)
        depth_spin.grid(row=0, column=1, sticky=tk.W, padx=(4, 0))

        ttk.Label(eval_frame, text="Time(s):").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self.time_var = tk.DoubleVar(value=self.engine.time_limit)
        time_spin = ttk.Spinbox(eval_frame, from_=0.5, to=30.0, increment=0.5,
                                textvariable=self.time_var, width=5)
        time_spin.grid(row=1, column=1, sticky=tk.W, padx=(4, 0), pady=(4, 0))

        ttk.Button(eval_frame, text="Analyze Position",
                   command=self._analyze).grid(row=2, column=0, columnspan=2, pady=(8, 0), sticky=tk.EW)

        self.eval_var = tk.StringVar(value="Eval: —")
        ttk.Label(eval_frame, textvariable=self.eval_var,
                  font=("Consolas", 10)).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        moves_frame = ttk.LabelFrame(right_frame, text="Move History", padding=4)
        moves_frame.pack(fill=tk.BOTH, expand=True)

        self.moves_text = tk.Text(moves_frame, width=28, height=20,
                                  font=("Consolas", 10), state=tk.DISABLED, wrap=tk.WORD)
        moves_scroll = ttk.Scrollbar(
            moves_frame, orient=tk.VERTICAL, command=self.moves_text.yview)
        self.moves_text.configure(yscrollcommand=moves_scroll.set)
        moves_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.moves_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _new_game(self, color):
        self.player_color = color
        self.flipped = (color == chess.BLACK)
        self.board = chess.Board()
        self.selected_square = None
        self.legal_targets = set()
        self.last_move = None
        self.game_over = False
        self.engine_thinking = False
        self._draw_board()
        self._update_info()
        self._clear_moves()
        if self.board.turn != self.player_color:
            self._engine_move()

    def _flip_board(self):
        self.flipped = not self.flipped
        self._draw_board()

    def _undo(self):
        if self.engine_thinking:
            return
        if len(self.board.move_stack) >= 2:
            self.board.pop()
            self.board.pop()
            self.last_move = None
            if self.board.move_stack:
                self.last_move = self.board.peek()
            self._draw_board()
            self._update_info()
            self._rebuild_moves()
        elif len(self.board.move_stack) == 1:
            self.board.pop()
            self.last_move = None
            self._draw_board()
            self._update_info()
            self._rebuild_moves()

    def _square_from_coords(self, x, y):
        col = x // 65
        row = y // 65
        if self.flipped:
            file_idx = 7 - col
            rank_idx = row
        else:
            file_idx = col
            rank_idx = 7 - row
        if 0 <= file_idx < 8 and 0 <= rank_idx < 8:
            return chess.square(file_idx, rank_idx)
        return None

    def _on_click(self, event):
        if self.engine_thinking or self.game_over:
            return
        if self.board.turn != self.player_color:
            return

        sq = self._square_from_coords(event.x, event.y)
        if sq is None:
            return

        if self.selected_square is not None and sq in self.legal_targets:
            move = chess.Move(self.selected_square, sq)
            if move in self.board.legal_moves:
                self._make_move(move)
                self.selected_square = None
                self.legal_targets = set()
                self._draw_board()
                if not self.game_over:
                    self.root.after(100, self._engine_move)
                return
            for promo in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
                promo_move = chess.Move(self.selected_square, sq, promotion=promo)
                if promo_move in self.board.legal_moves:
                    self._make_move(promo_move)
                    self.selected_square = None
                    self.legal_targets = set()
                    self._draw_board()
                    if not self.game_over:
                        self.root.after(100, self._engine_move)
                    return

        piece = self.board.piece_at(sq)
        if piece and piece.color == self.player_color:
            self.selected_square = sq
            self.legal_targets = set()
            for move in self.board.legal_moves:
                if move.from_square == sq:
                    self.legal_targets.add(move.to_square)
            self._draw_board()
        else:
            self.selected_square = None
            self.legal_targets = set()
            self._draw_board()

    def _make_move(self, move):
        san = self.board.san(move)
        self.board.push(move)
        self.last_move = move
        self._draw_board()
        self._update_info()
        self._add_move(san)
        if self.board.is_game_over():
            self.game_over = True
            self._show_game_over()

    def _engine_move(self):
        if self.game_over:
            return
        self.engine_thinking = True
        self.status_var.set("Engine thinking...")
        self.root.update_idletasks()

        def think():
            self.engine.time_limit = self.time_var.get()
            depth = self.depth_var.get()
            best_move, nodes = self.engine.find_best_move(self.board, max_depth=depth)
            self.root.after(0, lambda: self._apply_engine_move(best_move, nodes))

        thread = threading.Thread(target=think, daemon=True)
        thread.start()

    def _apply_engine_move(self, move, nodes):
        self.engine_thinking = False
        if move is None:
            self.status_var.set("Engine has no move")
            return
        san = self.board.san(move)
        self.board.push(move)
        self.last_move = move
        self._draw_board()
        self._update_info()
        self._add_move(san)
        if self.board.is_game_over():
            self.game_over = True
            self._show_game_over()

    def _show_game_over(self):
        result = self.board.result()
        if result == "1-0":
            msg = "White wins!"
        elif result == "0-1":
            msg = "Black wins!"
        else:
            msg = "Draw!"
        self.status_var.set(f"Game over: {msg}")
        messagebox.showinfo("Game Over", f"Result: {result}\n{msg}")

    def _draw_board(self):
        self.canvas.delete("all")
        for row in range(8):
            for col in range(8):
                x1 = col * 65
                y1 = row * 65
                x2 = x1 + 65
                y2 = y1 + 65
                color = LIGHT_SQ if (row + col) % 2 == 0 else DARK_SQ
                self.canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="")

        if self.last_move:
            self._highlight_square(self.last_move.from_square, MOVE_INDICATOR)
            self._highlight_square(self.last_move.to_square, MOVE_INDICATOR)

        if self.selected_square is not None:
            self._highlight_square(self.selected_square, SELECTED)
            for sq in self.legal_targets:
                self._draw_target_indicator(sq)

        for sq in chess.SQUARES:
            piece = self.board.piece_at(sq)
            if piece:
                self._draw_piece(sq, piece)

        for i in range(8):
            file_char = chr(ord('a') + i) if not self.flipped else chr(ord('h') - i)
            rank_char = str(8 - i) if not self.flipped else str(i + 1)
            self.canvas.create_text(i * 65 + 5, 8 * 65 - 5, text=file_char,
                                    anchor=tk.SW, font=("Segoe UI", 8), fill="#555")
            self.canvas.create_text(5, i * 65 + 5, text=rank_char,
                                    anchor=tk.NW, font=("Segoe UI", 8), fill="#555")

    def _highlight_square(self, sq, color):
        col = chess.square_file(sq)
        row = chess.square_rank(sq)
        if self.flipped:
            col = 7 - col
        else:
            row = 7 - row
        x1 = col * 65
        y1 = row * 65
        self.canvas.create_rectangle(x1, y1, x1 + 65, y1 + 65, fill=color, outline="")

    def _draw_target_indicator(self, sq):
        col = chess.square_file(sq)
        row = chess.square_rank(sq)
        if self.flipped:
            col = 7 - col
        else:
            row = 7 - row
        cx = col * 65 + 32
        cy = row * 65 + 32
        r = 6
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#333", outline="")

    def _draw_piece(self, sq, piece):
        col = chess.square_file(sq)
        row = chess.square_rank(sq)
        if self.flipped:
            col = 7 - col
        else:
            row = 7 - row
        x = col * 65 + 32
        y = row * 65 + 32
        symbol = PIECE_SYMBOLS[piece.symbol()]
        color = "#222" if piece.color == chess.WHITE else "#000"
        self.canvas.create_text(x, y, text=symbol, font=("Segoe UI", 36),
                                fill=color, anchor=tk.CENTER)

    def _update_info(self):
        turn = "White" if self.board.turn == chess.WHITE else "Black"
        self.turn_var.set(f"{turn} to move")
        if self.game_over:
            return
        if self.board.turn == self.player_color:
            self.status_var.set("Your turn")
        else:
            self.status_var.set("Engine thinking..." if self.engine_thinking else "Waiting for engine")

    def _add_move(self, san):
        self.moves_text.configure(state=tk.NORMAL)
        move_num = (len(self.board.move_stack) + 1) // 2
        if len(self.board.move_stack) % 2 == 1:
            self.moves_text.insert(tk.END, f"{move_num}. {san} ")
        else:
            self.moves_text.insert(tk.END, f"{san}\n")
        self.moves_text.see(tk.END)
        self.moves_text.configure(state=tk.DISABLED)

    def _rebuild_moves(self):
        self._clear_moves()
        temp_board = chess.Board()
        for i, move in enumerate(self.board.move_stack):
            san = temp_board.san(move)
            temp_board.push(move)
            move_num = (i + 2) // 2
            if i % 2 == 0:
                self.moves_text.configure(state=tk.NORMAL)
                self.moves_text.insert(tk.END, f"{move_num}. {san} ")
            else:
                self.moves_text.insert(tk.END, f"{san}\n")
                self.moves_text.configure(state=tk.DISABLED)

    def _clear_moves(self):
        self.moves_text.configure(state=tk.NORMAL)
        self.moves_text.delete("1.0", tk.END)
        self.moves_text.configure(state=tk.DISABLED)

    def _analyze(self):
        if self.engine_thinking:
            return
        self.engine_thinking = True
        self.status_var.set("Analyzing...")
        self.root.update_idletasks()

        def analyze():
            self.engine.time_limit = self.time_var.get()
            depth = self.depth_var.get()
            best_move, nodes = self.engine.find_best_move(self.board, max_depth=depth)
            if best_move:
                score = self.engine.evaluate(self.board)
                self.root.after(0, lambda: self._show_analysis(best_move, score, nodes))
            else:
                self.root.after(0, lambda: self._show_analysis(None, 0, 0))

        thread = threading.Thread(target=analyze, daemon=True)
        thread.start()

    def _show_analysis(self, best_move, score, nodes):
        self.engine_thinking = False
        if best_move:
            san = self.board.san(best_move)
            self.eval_var.set(f"Best: {san} | Eval: {score/100:+.2f} | Nodes: {nodes}")
            self.status_var.set(f"Analysis complete: {san}")
        else:
            self.eval_var.set("Eval: —")
            self.status_var.set("No legal moves")
        self._update_info()

    def run(self):
        self.root.mainloop()


def main():
    app = ChessPlayGUI()
    app.run()


if __name__ == "__main__":
    main()
