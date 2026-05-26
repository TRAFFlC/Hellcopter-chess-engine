import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import os
import sys

try:
    import chess
except ImportError:
    print("需要安装 python-chess: pip install chess")
    sys.exit(1)

try:
    import engine_wrapper as engine_lib
except ImportError:
    engine_lib = None


class PlayGUI:
    def __init__(self, engine_path=None):
        self.root = tk.Tk()
        self.root.title("Hellcopter 对弈")
        self.root.geometry("700x600")
        self.root.resizable(False, False)

        self.board = chess.Board()
        self.move_history = []
        self.result_queue = queue.Queue()
        self.player_color = chess.WHITE
        self.engine_busy = False
        self.game_over = False

        self.selected_square = None
        self.legal_moves_from_selected = []

        self.piece_symbols = {
            'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
            'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟'
        }

        self.setup_ui()
        self.start_engine()
        self.root.after(100, self.process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_frame = ttk.Frame(main_frame, padding="10")
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)

        canvas_frame = ttk.Frame(left_frame)
        canvas_frame.pack(pady=10)
        self.canvas = tk.Canvas(canvas_frame, width=400, height=400, bg='#f0d9b5')
        self.canvas.pack()
        self.canvas.bind('<Button-1>', self.on_click)

        self.status_label = ttk.Label(left_frame, text="你的回合 (白方)", font=('Arial', 14))
        self.status_label.pack(pady=10)

        history_frame = ttk.LabelFrame(left_frame, text="走法记录", padding="5")
        history_frame.pack(fill=tk.X, padx=10, pady=5)
        self.history_text = tk.Text(history_frame, width=50, height=6, font=('Courier', 10))
        self.history_text.pack(fill=tk.X)

        ttk.Label(right_frame, text="设置", font=('Arial', 12, 'bold')).pack(pady=(0, 10))

        ttk.Label(right_frame, text="引擎思考时间 (秒):").pack(anchor=tk.W)
        self.time_var = tk.StringVar(value="1.0")
        ttk.Entry(right_frame, textvariable=self.time_var, width=10).pack(anchor=tk.W, pady=5)

        ttk.Label(right_frame, text="搜索深度:").pack(anchor=tk.W)
        self.depth_var = tk.StringVar(value="20")
        ttk.Entry(right_frame, textvariable=self.depth_var, width=10).pack(anchor=tk.W, pady=5)

        ttk.Separator(right_frame, orient='horizontal').pack(fill=tk.X, pady=10)

        ttk.Button(right_frame, text="新对局 (执白)", command=lambda: self.new_game(chess.WHITE)).pack(fill=tk.X, pady=2)
        ttk.Button(right_frame, text="新对局 (执黑)", command=lambda: self.new_game(chess.BLACK)).pack(fill=tk.X, pady=2)
        ttk.Button(right_frame, text="撤销走法", command=self.undo_move).pack(fill=tk.X, pady=2)
        ttk.Button(right_frame, text="复制 FEN", command=self.copy_fen).pack(fill=tk.X, pady=2)

        ttk.Separator(right_frame, orient='horizontal').pack(fill=tk.X, pady=10)

        self.engine_status = ttk.Label(right_frame, text="引擎: 未连接", foreground='red')
        self.engine_status.pack(anchor=tk.W)

        self.draw_board()

    def draw_board(self):
        self.canvas.delete('all')
        colors = ['#f0d9b5', '#b58863']
        highlight_color = '#cdd26a'
        selected_color = '#829769'
        legal_move_color = '#646464'

        for rank in range(8):
            for file in range(8):
                x1 = file * 50
                y1 = (7 - rank) * 50
                x2 = x1 + 50
                y2 = y1 + 50

                color_idx = (rank + file) % 2
                fill = colors[color_idx]

                square = chess.square(file, rank)

                if self.selected_square == square:
                    fill = selected_color
                elif self.selected_square is not None:
                    for move in self.legal_moves_from_selected:
                        if move.to_square == square:
                            fill = highlight_color

                self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline='')

                piece = self.board.piece_at(square)
                if piece:
                    symbol = self.piece_symbols[piece.symbol()]
                    self.canvas.create_text(x1 + 25, y1 + 25, text=symbol, font=('Arial', 32), fill='white' if piece.color else 'black')

        for i in range(8):
            self.canvas.create_text(-10, 375 - i * 50, text=str(i + 1), font=('Arial', 10))
            self.canvas.create_text(i * 50 + 25, 410, text=chr(ord('a') + i), font=('Arial', 10))

    def on_click(self, event):
        if self.game_over or self.engine_busy:
            return
        if self.board.turn != self.player_color:
            return

        file = event.x // 50
        rank = 7 - (event.y // 50)
        if file < 0 or file > 7 or rank < 0 or rank > 7:
            return

        clicked_square = chess.square(file, rank)

        if self.selected_square is None:
            piece = self.board.piece_at(clicked_square)
            if piece and piece.color == self.player_color:
                self.selected_square = clicked_square
                self.legal_moves_from_selected = [m for m in self.board.legal_moves if m.from_square == clicked_square]
                self.draw_board()
        else:
            move = None
            for m in self.legal_moves_from_selected:
                if m.to_square == clicked_square:
                    move = m
                    break

            if move:
                if move.promotion:
                    move = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)

                self.make_move(move)
                self.selected_square = None
                self.legal_moves_from_selected = []
            else:
                piece = self.board.piece_at(clicked_square)
                if piece and piece.color == self.player_color:
                    self.selected_square = clicked_square
                    self.legal_moves_from_selected = [m for m in self.board.legal_moves if m.from_square == clicked_square]
                else:
                    self.selected_square = None
                    self.legal_moves_from_selected = []
                self.draw_board()

    def make_move(self, move):
        san = self.board.san(move)
        self.board.push(move)
        self.move_history.append(move.uci())
        self.draw_board()
        self.update_history()

        if self.board.is_game_over():
            self.game_over = True
            self.show_game_result()
            return

        if self.board.turn != self.player_color:
            self.status_label.config(text="引擎思考中...")
            self.engine_busy = True
            self.ask_engine()

    def ask_engine(self):
        fen = self.board.fen()
        time_limit = float(self.time_var.get())
        max_depth = int(self.depth_var.get())

        def engine_thread():
            try:
                move = self.get_engine_move(fen, time_limit, max_depth)
                if move:
                    self.result_queue.put(('move', move))
                else:
                    self.result_queue.put(('error', '引擎无回应'))
            except Exception as e:
                self.result_queue.put(('error', str(e)))

        threading.Thread(target=engine_thread, daemon=True).start()

    def get_engine_move(self, fen, time_limit, max_depth):
        if engine_lib and engine_lib.is_loaded():
            try:
                position_history = [engine_lib.compute_hash(fen)]
                uci_move, nodes = engine_lib.search(fen, time_limit, max_depth, position_history)
                if uci_move and uci_move != "0000":
                    return uci_move
                return None
            except Exception as e:
                print(f"引擎搜索错误: {e}")
                return None
        return None

    def process_queue(self):
        try:
            while True:
                result = self.result_queue.get_nowait()
                if result[0] == 'move':
                    move_uci = result[1]
                    try:
                        move = chess.Move.from_uci(move_uci)
                        if move in self.board.legal_moves:
                            san = self.board.san(move)
                            self.board.push(move)
                            self.move_history.append(move_uci)
                            self.draw_board()
                            self.update_history()

                            if self.board.is_game_over():
                                self.game_over = True
                                self.show_game_result()
                            else:
                                color_name = "白方" if self.board.turn == chess.WHITE else "黑方"
                                self.status_label.config(text=f"你的回合 ({color_name})")
                        else:
                            self.status_label.config(text=f"引擎返回非法走法: {move_uci}")
                    except Exception as e:
                        self.status_label.config(text=f"走法错误: {e}")
                    self.engine_busy = False
                elif result[0] == 'error':
                    self.status_label.config(text=f"引擎错误: {result[1]}")
                    self.engine_busy = False
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    def update_history(self):
        self.history_text.delete(1.0, tk.END)
        temp_board = chess.Board()
        moves_san = []
        for move_uci in self.move_history:
            move = chess.Move.from_uci(move_uci)
            san = temp_board.san(move)
            moves_san.append(san)
            temp_board.push(move)

        text = ""
        for i in range(0, len(moves_san), 2):
            move_num = i // 2 + 1
            text += f"{move_num}. {moves_san[i]}"
            if i + 1 < len(moves_san):
                text += f" {moves_san[i + 1]}"
            text += "\n"
        self.history_text.insert(tk.END, text)

    def show_game_result(self):
        result = self.board.result()
        if result == '1-0':
            msg = "白方获胜！" if self.player_color == chess.WHITE else "引擎获胜！"
        elif result == '0-1':
            msg = "黑方获胜！" if self.player_color == chess.BLACK else "引擎获胜！"
        else:
            msg = "和棋！"
        self.status_label.config(text=msg)
        messagebox.showinfo("对局结束", msg)

    def new_game(self, player_color):
        self.board = chess.Board()
        self.move_history = []
        self.player_color = player_color
        self.game_over = False
        self.engine_busy = False
        self.selected_square = None
        self.legal_moves_from_selected = []
        self.draw_board()
        self.history_text.delete(1.0, tk.END)

        if player_color == chess.WHITE:
            self.status_label.config(text="你的回合 (白方)")
        else:
            self.status_label.config(text="引擎思考中...")
            self.engine_busy = True
            self.ask_engine()

    def undo_move(self):
        if self.engine_busy or self.game_over:
            return
        if len(self.move_history) >= 2:
            self.board.pop()
            self.board.pop()
            self.move_history.pop()
            self.move_history.pop()
        elif len(self.move_history) == 1:
            self.board.pop()
            self.move_history.pop()
        else:
            return

        self.selected_square = None
        self.legal_moves_from_selected = []
        self.draw_board()
        self.update_history()
        self.status_label.config(text="你的回合" + (" (白方)" if self.board.turn == chess.WHITE else " (黑方)"))

    def copy_fen(self):
        fen = self.board.fen()
        self.root.clipboard_clear()
        self.root.clipboard_append(fen)
        self.status_label.config(text="FEN 已复制")

    def start_engine(self):
        if engine_lib:
            if engine_lib.init():
                self.engine_status.config(text="引擎: 已连接 (DLL)", foreground='green')
            else:
                self.engine_status.config(text="引擎: 初始化失败", foreground='red')
        else:
            self.engine_status.config(text="引擎: engine_wrapper 未导入", foreground='red')

    def on_close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    app = PlayGUI()
    app.run()


if __name__ == "__main__":
    main()
