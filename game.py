import chess
import time
import logging
import random
import numpy as np
import cv2
import os

from screen import find_and_click, wait_for, click_position, take_screenshot, find_template
from board import find_board_region, create_initial_board, detect_move_by_image_diff, detect_game_over, wait_for_board_stable, _compute_change_map
from engine import find_best_move
from config import *
import engine_wrapper

_flipped = False


def _push_move_with_history(board, move, position_history):
    board.push(move)
    if position_history is not None:
        try:
            h = engine_wrapper.compute_hash(board.fen())
            position_history.append(h)
        except Exception:
            pass


def _verify_move_executed(prev_screenshot, board_region, square_size, move, board, threshold=0.08):
    left, top, width, height = board_region
    prev_board = prev_screenshot[top:top+height, left:left+width]
    curr_screenshot = wait_for_board_stable(board_region, timeout=0.6)
    curr_board = curr_screenshot[top:top+height, left:left+width]

    change_map = _compute_change_map(prev_board, curr_board, square_size, _flipped)

    from_changed = change_map.get(move.from_square, 0) > threshold
    to_changed = change_map.get(move.to_square, 0) > threshold

    return from_changed and to_changed, curr_screenshot, change_map


def start_new_game():
    result = find_and_click(UI_TEMPLATES["new_game"])
    if result:
        time.sleep(GAME_START_DELAY)
    return result


def select_time_control():
    result = wait_for(UI_TEMPLATES["five_plus_two"], timeout=WAIT_TIMEOUT)
    if result:
        time.sleep(GAME_START_DELAY)
    return result


def make_move_on_screen(move, board_region, square_size, delay_range=None):
    global _flipped
    from_square = move.from_square
    to_square = move.to_square

    from_file = chess.square_file(from_square)
    from_rank = chess.square_rank(from_square)
    to_file = chess.square_file(to_square)
    to_rank = chess.square_rank(to_square)

    if _flipped:
        from_x = board_region[0] + (7 - from_file) * \
            square_size + square_size // 2
        from_y = board_region[1] + from_rank * square_size + square_size // 2
        to_x = board_region[0] + (7 - to_file) * square_size + square_size // 2
        to_y = board_region[1] + to_rank * square_size + square_size // 2
    else:
        from_x = board_region[0] + from_file * square_size + square_size // 2
        from_y = board_region[1] + (7 - from_rank) * \
            square_size + square_size // 2
        to_x = board_region[0] + to_file * square_size + square_size // 2
        to_y = board_region[1] + (7 - to_rank) * square_size + square_size // 2

    if delay_range is not None:
        delay_min, delay_max = delay_range
    else:
        delay_min, delay_max = MOVE_DELAY_MIN, MOVE_DELAY_MAX

    click_position(from_x, from_y)
    time.sleep(random.uniform(delay_min, delay_max))
    click_position(to_x, to_y)

    if move.promotion is not None:
        time.sleep(random.uniform(0.6, 1.0))
        is_white_promotion = chess.square_rank(to_square) == 7
        template_key = "white_promotion_queen" if is_white_promotion else "black_promotion_queen"
        template_path = UI_TEMPLATES[template_key]
        for attempt in range(5):
            matches = find_template(template_path, threshold=0.7)
            if matches:
                mx, my, mw, mh = matches[0]
                click_position(mx + mw // 2, my + mh // 2)
                logging.info(f"Promotion queen icon clicked (attempt {attempt+1})")
                break
            time.sleep(0.3)
        else:
            logging.warning("Promotion queen icon not found, clicking destination as fallback")
            click_position(to_x, to_y)


def wait_for_opponent_move(prev_screenshot, board_region, square_size, board, my_color, stop_callback=None, timeout=300):
    logging.info("Waiting for opponent move...")

    check_count = 0
    fast_check_limit = 10
    start_time = time.time()

    while True:
        if stop_callback and stop_callback():
            return None

        if time.time() - start_time > timeout:
            logging.warning(f"Opponent move timeout after {timeout}s ({check_count} checks)")
            return None

        if check_count < fast_check_limit:
            time.sleep(0.1)
        else:
            time.sleep(0.3)

        curr_screenshot = wait_for_board_stable(board_region, timeout=0.3)

        if detect_game_over(curr_screenshot):
            logging.info("Game over detected")
            return "game_over"

        move = detect_move_by_image_diff(
            prev_screenshot, curr_screenshot, board_region, square_size, board, flipped=_flipped)

        if move is not None:
            logging.info(f"Detected opponent move: {board.san(move)}")
            return move

        check_count += 1

        if check_count % 5 == 0:
            logging.info(
                f"Still waiting for opponent... ({check_count} checks)")


def play_game(stop_callback=None, infinite_wait=False, delay_callback=None, max_depth=None, time_limit=None):
    global _flipped

    logging.info("Starting new game")
    engine_wrapper.reload_library()

    if not start_new_game():
        logging.error(
            "Failed to start new game - trying to return to main menu")
        _return_to_main_menu()
        return

    if not select_time_control():
        logging.error(
            "Failed to select time control - trying to return to main menu")
        _return_to_main_menu()
        return

    time.sleep(GAME_START_DELAY * 1.5)

    board_region = None
    square_size = None
    my_color = None
    max_attempts = int(BOARD_DETECTION_TIMEOUT / BOARD_DETECTION_INTERVAL)
    attempt = 0

    while True:
        if stop_callback and stop_callback():
            logging.info("Stop requested during board detection")
            return

        time.sleep(BOARD_DETECTION_INTERVAL)
        screenshot = take_screenshot()
        board_region, square_size, my_color = find_board_region(screenshot)

        if board_region is not None:
            break

        attempt += 1
        if not infinite_wait and attempt >= max_attempts:
            break

        if infinite_wait:
            logging.warning(
                f"Board detection attempt {attempt} failed, retrying (infinite mode)...")
        else:
            logging.warning(
                f"Board detection attempt {attempt}/{max_attempts} failed, retrying...")

    if board_region is None:
        logging.error(
            "Could not find board region - trying to return to main menu")
        _return_to_main_menu()
        return

    left, top, width, height = board_region

    if my_color is None:
        my_color = chess.WHITE
        _flipped = False
    else:
        _flipped = (my_color == chess.BLACK)

    color_name = "white" if my_color == chess.WHITE else "black"
    orientation = "flipped" if _flipped else "normal"
    logging.info(f"Playing as {color_name}, board orientation: {orientation}")

    board = create_initial_board()
    logging.info(f"Initial board: {board.fen()}")

    position_history = []
    try:
        initial_hash = engine_wrapper.compute_hash(board.fen())
        position_history.append(initial_hash)
    except Exception:
        position_history = []

    board_synced = True

    if my_color == chess.BLACK:
        opening_path = os.path.join(IMAGE_DIR, "black_opening.png")
        opening_img = cv2.imread(opening_path)
        if opening_img is not None:
            if opening_img.shape[0] != height or opening_img.shape[1] != width:
                opening_img = cv2.resize(opening_img, (width, height))
            prev_screenshot = np.zeros(
                (screenshot.shape[0], screenshot.shape[1], 3), dtype=np.uint8)
            prev_screenshot[top:top+height, left:left+width] = opening_img
            logging.info(
                "Using black_opening.png as reference for opponent's first move")

            from board import infer_move_from_diff
            inferred_move = infer_move_from_diff(
                screenshot, board_region, square_size, board, flipped=_flipped)
            if inferred_move:
                logging.info(
                    f"Inferred opponent's first move: {inferred_move.uci()}")
                _push_move_with_history(board, inferred_move, position_history)
                prev_screenshot = wait_for_board_stable(board_region, timeout=1.0)
            else:
                logging.warning(
                    "Failed to infer opening move - retrying with fresh screenshot")
                time.sleep(1.0)
                fresh_screenshot = wait_for_board_stable(board_region, timeout=1.0)
                inferred_move = infer_move_from_diff(
                    fresh_screenshot, board_region, square_size, board, flipped=_flipped)
                if inferred_move:
                    logging.info(
                        f"Inferred opponent's first move on retry: {inferred_move.uci()}")
                    _push_move_with_history(board, inferred_move, position_history)
                    prev_screenshot = wait_for_board_stable(board_region, timeout=1.0)
                else:
                    logging.warning(
                        "Failed to infer opening move after retry. "
                        "Board state may be out of sync - will attempt re-sync in game loop.")
                    board_synced = False
                    prev_screenshot = wait_for_board_stable(board_region, timeout=1.0)
        else:
            time.sleep(0.5)
            prev_screenshot = wait_for_board_stable(board_region, timeout=1.0)
    else:
        time.sleep(0.5)
        prev_screenshot = wait_for_board_stable(board_region, timeout=1.0)

    while True:
        if stop_callback and stop_callback():
            logging.info("Stop requested")
            break

        if not board_synced:
            logging.info("Attempting board re-sync...")
            from board import infer_move_from_diff
            fresh_screenshot = wait_for_board_stable(board_region, timeout=1.0)
            inferred_move = infer_move_from_diff(
                fresh_screenshot, board_region, square_size, board, flipped=_flipped)
            if inferred_move:
                logging.info(f"Re-sync: detected move {inferred_move.uci()}")
                _push_move_with_history(board, inferred_move, position_history)
                board_synced = True
                prev_screenshot = wait_for_board_stable(board_region, timeout=1.0)
                logging.info("Board re-synced successfully")
                continue
            else:
                logging.warning("Re-sync failed - waiting for opponent to move")
                result = wait_for_opponent_move(
                    prev_screenshot, board_region, square_size, board, my_color,
                    stop_callback, timeout=15
                )
                if result is None:
                    logging.warning(
                        "No move detected during re-sync wait - board still unsynced, retrying re-sync")
                    board_synced = False
                    prev_screenshot = wait_for_board_stable(board_region, timeout=1.0)
                    continue
                if result == "game_over":
                    break
                logging.info(f"Re-sync: detected move during wait: {result.uci()}")
                _push_move_with_history(board, result, position_history)
                board_synced = True
                prev_screenshot = take_screenshot()
                continue

        if board.turn == my_color:
            logging.debug(f"Engine input FEN: {board.fen()}")
            move = find_best_move(board, max_depth=max_depth, time_limit=time_limit,
                                  position_history=position_history)

            if move is None:
                logging.warning("No legal move found!")
                break

            logging.info(f"Making move: {board.san(move)}")
            delay_range = delay_callback() if delay_callback else None

            pre_move_screenshot = wait_for_board_stable(board_region, timeout=0.5)

            max_retries = 3
            move_confirmed = False
            for attempt in range(max_retries):
                make_move_on_screen(move, board_region, square_size, delay_range)

                confirmed, post_move_screenshot, change_map = _verify_move_executed(
                    pre_move_screenshot, board_region, square_size, move, board
                )

                if confirmed:
                    move_confirmed = True
                    prev_screenshot = post_move_screenshot
                    break

                from_ratio = change_map.get(move.from_square, 0)
                to_ratio = change_map.get(move.to_square, 0)
                logging.warning(
                    f"Move {board.san(move)} not confirmed on screen "
                    f"(attempt {attempt+1}/{max_retries}, "
                    f"from_change={from_ratio:.2f}, to_change={to_ratio:.2f})")

                time.sleep(0.5)
                pre_move_screenshot = wait_for_board_stable(board_region, timeout=0.5)

            if not move_confirmed:
                logging.error(
                    f"Move {board.san(move)} failed after {max_retries} attempts - "
                    f"board state may be out of sync")
                board_synced = False

            if not move_confirmed:
                logging.warning(
                    "Skipped internal board push because move was not confirmed on screen")
                prev_screenshot = wait_for_board_stable(board_region, timeout=1.0)
                continue
            _push_move_with_history(board, move, position_history)
            logging.debug(f"Board after our confirmed move: {board.fen()}")

            if board.is_game_over():
                logging.info("Game over (we won/lost/draw)")
                break
        else:
            result = wait_for_opponent_move(
                prev_screenshot, board_region, square_size, board, my_color, stop_callback
            )

            if result is None:
                logging.info("Stop requested during opponent wait")
                break

            if result == "game_over":
                break

            _push_move_with_history(board, result, position_history)
            logging.debug(f"Board after opponent move: {board.fen()}")
            prev_screenshot = wait_for_board_stable(board_region, timeout=0.8)

            if board.is_game_over():
                logging.info("Game over")
                break

    if not (stop_callback and stop_callback()):
        time.sleep(1)
        handle_game_over()
    logging.info("Game finished")


def handle_game_over():
    screenshot = take_screenshot()
    if not detect_game_over(screenshot):
        for _ in range(3):
            if find_and_click(UI_TEMPLATES["close"]):
                break
            time.sleep(0.5)

    time.sleep(GAME_START_DELAY)
    find_and_click(UI_TEMPLATES["back"])
    time.sleep(GAME_START_DELAY)


def _return_to_main_menu():
    logging.info("Attempting to return to main menu...")
    time.sleep(1)
    for _ in range(3):
        if find_and_click(UI_TEMPLATES["close"]):
            time.sleep(CLICK_DELAY)
        if find_and_click(UI_TEMPLATES["back"]):
            time.sleep(CLICK_DELAY)
            break
        time.sleep(0.5)
