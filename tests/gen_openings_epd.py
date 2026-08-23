"""生成对弈用开局多样化 EPD 文件（比赛不加载 book，用多样化起点保证开局公平与多样）。

来源: 标准开局树（主流变例，深度 4-8 步），非任何引擎的私有开局库。
用法:
    py tests/gen_openings_epd.py [输出路径] [数量]
"""
import random
import sys

OPENING_LINES = [
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1e2 f8e7",          # Ruy Lopez Closed
    "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6",          # Open Sicilian Najdorf
    "e2e4 c7c5 g1f3 b8c6 d2d4 c5d4 f3d4 g8f6 b1c3 e7e5",          # Sicilian Classical
    "e2e4 c7c6 d2d4 d7d5 e4d5 c6d5 c2c4 d5b4 c4e5 g8f6",          # Caro-Kann Advance
    "e2e4 e7e6 d2d4 d7d5 b1c3 g8f6 c1g5 f8e7 e4e5 f6d7",          # French Classical
    "d2d4 d7d5 c2c4 e7e6 b1c3 g8f6 c1g5 f8e7 e2e3 e8g8",          # QGD Main
    "d2d4 g8f6 c2c4 e7e6 b1c3 d7d5 c4d5 e6d5 c1g5 f8e7",          # QID/Slav complex
    "d2d4 g8f6 c2c4 g7g6 b1c3 f8g7 e2e4 d7d6 g1f3 e8g8",          # KID Main
    "d2d4 g8f6 c2c4 g7g6 b1c3 d7d5 c4d5 f6d5 e2e4 d5c3",          # Grünfeld Exchange
    "d2d4 d7d5 c2c4 c7c6 g1f3 g8f6 b1c3 e7e6 e2e3 b8d7",          # Semi-Slav
    "d2d4 f7f5 g1f3 g8f6 g2g3 e7e6 f1g2 f8e7 e1g1 e8g8",          # Dutch Leningrad
    "c2c4 e7e5 b1c3 g8f6 g1f3 b8c6 g2g3 d7d6 f1g2 f8e7",          # English Reversed Dragon
    "g1f3 d7d5 d2d4 g8f6 c2c4 e7e6 b1c3 f8e7 c1f4 e8g8",          # Catalan-ish
    "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 c2c3 g8f6 d2d3 d7d6",          # Italian Giuoco
    "e2e4 e7e5 g1f3 b8c6 d2d4 e5d4 f3d4 g8f6 d4c6 b7c6",          # Scotch
    "e2e4 g7g6 d2d4 f8g7 b1c3 d7d6 f2f4 g8f6 g1f3 e8g8",          # Pirc
    "e2e4 d7d6 d2d4 g8f6 b1c3 g7g6 g1f3 f8g7 f1e2 e8g8",          # Modern
    "d2d4 e7e5 d4e5 d8e7 b1c3 e7e5 g1f3 f7f5 f1c4 f5f4",          # Latvian/Englund area
    "e2e4 e7e5 f1c4 g8f6 d2d3 b8c6 g1f3 f8c5 c2c3 d7d6",          # Italian Slow
    "d2d4 d7d5 g1f3 g8f6 c2c4 e7e6 b1c3 c7c5 d4d5 e6d5",          # Benoni structure
    "c2c4 c7c5 g1f3 g8f6 d2d4 c5d4 f3d4 e7e6 b1c3 d7d6",          # Symmetrical English
    "e2e4 g8f6 e4e5 f6d5 d2d4 d7d6 g1f3 f8e7 f1c4 d5b6",          # Alekhine 4.pawn
    "d2d4 g8f6 g1f3 e7e6 c2c4 b7b6 g2g3 c8b7 f1g2 f8e7",          # QID Classical
    "e2e4 c7c5 g1f3 e7e6 d2d4 c5d4 f3d4 b8c6 b1c3 d8c7",          # Sicilian Taimanov
    "e2e4 c7c5 g1f3 f8e7 f1c4 g8f6 d2d3 d7d6 e1g1 e8g8",          # Sicilian 2...e6 slow
    "d2d4 f7f5 c2c4 g8f6 g1f3 e7e6 b1c3 d7d5 c4d5 e6d5",          # Stonewall Dutch
    "e2e4 e7e5 g1f3 g8f6 f3e5 d7d6 e5f3 f6e4 d2d4 d6d5",          # Petroff
    "d2d4 e7e6 c2c4 d7d5 b1c3 g8f6 c1g5 f8e7 e2e3 e8g8",          # QGD 3.Nc3 Nf6
    "e2e4 b8c6 d2d4 d7d5 e4d5 c6d5 b1c3 g8f6 g1f3 f8g4",          # Nimzowitsch Def
    "g1f3 g8f6 c2c4 e7e6 b2b3 d7d5 c1b2 f8e7 e2e3 e8g8",          # Réxi/QID hybrid
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "arena/openings.epd"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    rng = random.Random(20260823)
    import chess
    lines = []
    for _ in range(n):
        uci_line = rng.choice(OPENING_LINES)
        board = chess.Board()
        for mv in uci_line.split():
            board.push(chess.Move.from_uci(mv))
        lines.append(board.epd())
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"写入 {len(lines)} 个开局到 {out}")


if __name__ == "__main__":
    main()
