import cv2
import numpy as np
import chess
import os
import time
from config import IMAGE_DIR, TEMPLATE_THRESHOLD, BOARD_SIZE, UI_TEMPLATES
from screen import find_template, take_screenshot


def _detect_square_size_by_color_scan(img, start_x, start_y, template_w, template_h):
    h, w = img.shape[:2]
    center_x = start_x + template_w // 2
    center_y = start_y + template_h // 2
    
    sample_x = min(max(center_x, 0), w - 1)
    sample_y = min(max(center_y, 0), h - 1)
    base_color = img[sample_y, sample_x].astype(np.float32)
    
    square_w = template_w
    for dx in range(1, min(150, w - center_x)):
        test_x = center_x + dx
        if test_x >= w - 5:
            break
        colors = []
        for offset in range(-3, 4):
            if 0 <= test_x + offset < w:
                colors.append(img[sample_y, test_x + offset].astype(np.float32))
        if not colors:
            continue
        avg_color = np.mean(colors, axis=0)
        diff = np.mean(np.abs(avg_color - base_color))
        if diff > 25:
            square_w = dx
            break
    
    square_h = template_h
    for dy in range(1, min(150, h - center_y)):
        test_y = center_y + dy
        if test_y >= h - 5:
            break
        colors = []
        for offset in range(-3, 4):
            if 0 <= test_y + offset < h:
                colors.append(img[test_y + offset, sample_x].astype(np.float32))
        if not colors:
            continue
        avg_color = np.mean(colors, axis=0)
        diff = np.mean(np.abs(avg_color - base_color))
        if diff > 25:
            square_h = dy
            break
    
    return square_w, square_h


def _find_board_edges(img, match_x, match_y, square_size):
    h, w = img.shape[:2]
    
    left_edge = match_x
    for x in range(match_x, -1, -1):
        if x < square_size:
            left_edge = 0
            break
        left_edge = x - (x % square_size)
        break
    
    top_edge = match_y
    for y in range(match_y, -1, -1):
        if y < square_size:
            top_edge = 0
            break
        top_edge = y - (y % square_size)
        break
    
    return left_edge, top_edge


def find_board_region(screenshot):
    opening_templates = [
        ("white_opening.png", chess.WHITE),
        ("black_opening.png", chess.BLACK),
    ]
    
    for template_name, color in opening_templates:
        template_path = os.path.join(IMAGE_DIR, template_name)
        template = cv2.imread(template_path)
        if template is None:
            continue
        
        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        if max_val >= 0.5:
            th, tw = template.shape[:2]
            square_size = tw // BOARD_SIZE
            return (max_loc[0], max_loc[1], tw, th), square_size, color
    
    gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=2)
    edges = cv2.erode(edges, kernel, iterations=1)
    
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 200000:
            continue
        
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        
        if len(approx) != 4:
            continue
        
        x, y, w, h = cv2.boundingRect(approx)
        aspect_ratio = float(w) / h if h > 0 else 0
        
        if aspect_ratio < 0.9 or aspect_ratio > 1.1:
            continue
        
        candidates.append((x, y, w, h, area))
    
    if not candidates:
        return None, None, None
    
    candidates.sort(key=lambda c: c[4], reverse=True)
    
    x, y, w, h, _ = candidates[0]
    
    square_size = w // BOARD_SIZE
    
    return (x, y, w, h), square_size, None


def create_initial_board():
    return chess.Board()


def wait_for_board_stable(board_region, timeout=0.6, stability_threshold=0.003, check_interval=0.05):
    """Wait until the board stops changing (animation finished).

    Returns the last stable screenshot, or the last screenshot if timeout.
    """
    import logging
    left, top, width, height = board_region

    prev = take_screenshot()
    start = time.time()
    stable_count = 0
    required_stable = 2  # Require 2 consecutive stable frames

    while time.time() - start < timeout:
        time.sleep(check_interval)
        curr = take_screenshot()

        prev_board = prev[top:top + height, left:left + width]
        curr_board = curr[top:top + height, left:left + width]
        diff = cv2.absdiff(prev_board, curr_board)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
        changed = np.count_nonzero(thresh)
        total = thresh.size
        ratio = changed / total if total > 0 else 0

        if ratio < stability_threshold:
            stable_count += 1
            if stable_count >= required_stable:
                return curr
        else:
            stable_count = 0

        prev = curr

    return curr


def _compute_change_map(prev_board_img, curr_board_img, square_size, flipped):
    diff = cv2.absdiff(prev_board_img, curr_board_img)
    gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray_diff, 30, 255, cv2.THRESH_BINARY)

    def get_sq(row, col):
        if flipped:
            return chess.square(7 - col, row)
        else:
            return chess.square(col, 7 - row)

    change_map = {}
    for row in range(8):
        for col in range(8):
            y1 = row * square_size
            y2 = (row + 1) * square_size
            x1 = col * square_size
            x2 = (col + 1) * square_size
            cell = thresh[y1:y2, x1:x2]
            changed_pixels = np.count_nonzero(cell)
            total_pixels = cell.size
            sq = get_sq(row, col)
            change_map[sq] = changed_pixels / total_pixels if total_pixels > 0 else 0

    return change_map


def _get_affected_squares(board, move):
    affected = {move.from_square, move.to_square}
    if board.is_castling(move):
        king_from = move.from_square
        king_to = move.to_square
        if king_to > king_from:
            rook_from = king_from + 3
            rook_to = king_from + 1
        else:
            rook_from = king_from - 4
            rook_to = king_from - 1
        affected = {king_from, king_to, rook_from, rook_to}
    elif board.is_en_passant(move):
        captured_sq = move.to_square - 8 if board.turn == chess.WHITE else move.to_square + 8
        affected = {move.from_square, move.to_square, captured_sq}
    return affected


def _score_move(change_map, board, move):
    affected = _get_affected_squares(board, move)
    from_ratio = change_map.get(move.from_square, 0)
    to_ratio = change_map.get(move.to_square, 0)
    other_ratio = sum(
        change_map.get(sq, 0) for sq in affected - {move.from_square, move.to_square}
    )
    score = from_ratio * 2.0 + to_ratio * 1.5 + other_ratio
    return score


def _find_best_move_by_scoring(change_map, board, significant, require_all_significant_for_special=True):
    import logging

    best_move = None
    best_score = -1
    second_best_score = -1
    best_affected = set()

    for move in board.legal_moves:
        affected = _get_affected_squares(board, move)

        is_special = board.is_castling(move) or board.is_en_passant(move)
        if is_special and require_all_significant_for_special:
            if not affected <= significant:
                continue

        score = _score_move(change_map, board, move)

        if score > best_score:
            second_best_score = best_score
            best_score = score
            best_move = move
            best_affected = affected
        elif score > second_best_score:
            second_best_score = score

    return best_move, best_score, second_best_score, best_affected


def detect_move_by_image_diff(prev_screenshot, curr_screenshot, board_region, square_size, board, flipped=False):
    import logging

    left, top, width, height = board_region
    prev_board = prev_screenshot[top:top+height, left:left+width]
    curr_board = curr_screenshot[top:top+height, left:left+width]

    change_map = _compute_change_map(prev_board, curr_board, square_size, flipped)

    significant = {sq for sq, ratio in change_map.items() if ratio > 0.08}
    if not significant:
        return None

    sorted_changes = sorted(change_map.items(), key=lambda x: x[1], reverse=True)
    top_display = [(chess.square_name(sq), f"{ratio:.2f}")
                   for sq, ratio in sorted_changes[:8] if ratio > 0.05]
    logging.info(f"Changed squares: {top_display}")

    if len(significant) < 2:
        return None

    avg_change = sum(change_map.values()) / len(change_map) if change_map else 0

    best_move, best_score, second_best_score, best_affected = _find_best_move_by_scoring(
        change_map, board, significant, require_all_significant_for_special=True
    )

    if best_move is None:
        logging.info("No legal move matches observed changes")
        return None

    margin = (best_score - second_best_score) / best_score if best_score > 0 else 0
    min_threshold = max(avg_change * 3, 0.15)

    move_type = ""
    if board.is_castling(best_move):
        move_type = " [castling]"
    elif board.is_en_passant(best_move):
        move_type = " [en passant]"

    logging.info(
        f"Best candidate: {best_move.uci()}{move_type} "
        f"(score={best_score:.3f}, 2nd={second_best_score:.3f}, "
        f"margin={margin:.1%}, threshold={min_threshold:.3f})")

    if best_score < min_threshold:
        logging.info("Score below minimum threshold")
        return None

    if margin < 0.10 and len(significant) > 4:
        logging.info(f"Insufficient margin ({margin:.1%}) with {len(significant)} changed squares")
        return None

    coverage = sum(change_map.get(sq, 0) for sq in best_affected)
    total_sig = sum(r for r in change_map.values() if r > 0.02)
    coverage_ratio = coverage / total_sig if total_sig > 0 else 0
    if coverage_ratio < 0.3 and len(significant) > 4:
        logging.info(
            f"Low coverage ({coverage_ratio:.1%}) - move explains too little of total change")
        return None

    logging.info(f"Detected move: {best_move.uci()}{move_type}")
    return best_move


def infer_move_from_diff(screenshot, board_region, square_size, board, flipped=False):
    import logging

    left, top, width, height = board_region
    board_img = screenshot[top:top+height, left:left+width]

    opening_path = os.path.join(IMAGE_DIR, "black_opening.png")
    opening_img = cv2.imread(opening_path)

    if opening_img is None:
        return None

    if opening_img.shape[0] != height or opening_img.shape[1] != width:
        opening_img = cv2.resize(opening_img, (width, height))

    change_map = _compute_change_map(opening_img, board_img, square_size, flipped)

    sorted_squares = sorted(change_map.items(), key=lambda x: x[1], reverse=True)
    top_changed = [(chess.square_name(sq), f"{ratio:.3f}")
                   for sq, ratio in sorted_squares[:8] if ratio > 0.05]
    logging.info(f"Changed squares from opening: {[name for name, _ in top_changed]}")
    logging.info(f"Change ratios: {dict(top_changed)}")

    significant = {sq for sq, ratio in change_map.items() if ratio > 0.08}

    if len(significant) < 2:
        return None

    avg_change = sum(change_map.values()) / len(change_map) if change_map else 0

    best_move, best_score, second_best_score, best_affected = _find_best_move_by_scoring(
        change_map, board, significant, require_all_significant_for_special=True
    )

    if best_move is None:
        logging.info("Could not infer move from changed squares")
        return None

    margin = (best_score - second_best_score) / best_score if best_score > 0 else 0
    min_threshold = max(avg_change * 2, 0.10)

    move_type = ""
    if board.is_castling(best_move):
        move_type = " [castling]"
    elif board.is_en_passant(best_move):
        move_type = " [en passant]"

    logging.info(
        f"Opening best candidate: {best_move.uci()}{move_type} "
        f"(score={best_score:.3f}, 2nd={second_best_score:.3f}, "
        f"margin={margin:.1%}, threshold={min_threshold:.3f})")

    if best_score < min_threshold:
        logging.info("Score below minimum threshold for opening inference")
        return None

    if margin < 0.10 and len(significant) > 4:
        logging.info(f"Insufficient margin ({margin:.1%}) for opening inference")
        return None

    logging.info(f"Inferred opening move: {best_move.uci()}{move_type}")
    return best_move


def detect_game_over(screenshot):
    close_template = UI_TEMPLATES.get("close")
    if close_template is None:
        return False
    matches = find_template(close_template, screenshot, threshold=TEMPLATE_THRESHOLD)
    return len(matches) > 0
