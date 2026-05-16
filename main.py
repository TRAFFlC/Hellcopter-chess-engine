import argparse
import logging
import sys

def main():
    parser = argparse.ArgumentParser(description="Hellcopter Chess Engine")
    parser.add_argument("--gui", action="store_true", help="Run GUI")
    parser.add_argument("--uci", action="store_true", help="Run as UCI engine")
    parser.add_argument("--fen", type=str, help="FEN position to analyze")
    parser.add_argument("--depth", type=int, default=10, help="Max search depth")
    parser.add_argument("--time", type=float, default=2.0, help="Time limit in seconds")
    args = parser.parse_args()

    if args.uci:
        from uci_engine import main as uci_main
        uci_main()
    elif args.gui:
        from gui import main as gui_main
        gui_main()
    elif args.fen:
        import engine_wrapper as ew
        ew.reload_library()
        move, score, nodes = ew.search_with_score(args.fen, args.time, args.depth)
        print(f"Move: {move}")
        print(f"Score: {score}")
        print(f"Nodes: {nodes:,}")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
