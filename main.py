import argparse
import logging
import time
from config import LOG_LEVEL, ENGINE_MAX_DEPTH, ENGINE_TIME_LIMIT
from game import play_game


def run_cli(games, max_depth, time_limit):
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                        level=getattr(logging, LOG_LEVEL, logging.INFO))
    logger = logging.getLogger(__name__)

    logger.info("Starting chess bot - Games: %s, Depth: %d, Time: %.1fs",
                "infinite" if games == 0 else str(games), max_depth, time_limit)

    game_count = 0
    try:
        while games == 0 or game_count < games:
            game_count += 1
            logger.info("Game %d starting", game_count)
            try:
                play_game(max_depth=max_depth, time_limit=time_limit)
            except Exception as e:
                logger.error("Error during game %d: %s", game_count, e)
            logger.info("Game %d ended", game_count)
            if games == 0 or game_count < games:
                time.sleep(2)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")


def main():
    parser = argparse.ArgumentParser(description="Automated Chess Bot")
    parser.add_argument("--games", "-g", type=int, default=0,
                        help="Number of games to play (0 = infinite)")
    parser.add_argument("--depth", "-d", type=int, default=ENGINE_MAX_DEPTH,
                        help=f"Max search depth (default: {ENGINE_MAX_DEPTH})")
    parser.add_argument("--time", "-t", type=float, default=ENGINE_TIME_LIMIT,
                        help=f"Time limit per move in seconds (default: {ENGINE_TIME_LIMIT})")
    parser.add_argument("--cli", action="store_true",
                        help="Run in CLI mode (no GUI)")
    args = parser.parse_args()

    if args.cli:
        run_cli(args.games, args.depth, args.time)
    else:
        from gui import ChessBotGUI
        app = ChessBotGUI()
        app.run()


if __name__ == "__main__":
    main()
