CLICK_DELAY: float = 0.3
MOVE_DELAY_MIN: float = 0.5
MOVE_DELAY_MAX: float = 5.5
GAME_START_DELAY: float = 2.0
TURN_CHECK_INTERVAL: float = 1.0
TEMPLATE_THRESHOLD: float = 0.8
WAIT_TIMEOUT: float = 10.0
WAIT_INTERVAL: float = 0.5
IMAGE_DIR: str = "."
BOARD_SIZE: int = 8
BOARD_DETECTION_TIMEOUT: float = 120.0
BOARD_DETECTION_INTERVAL: float = 0.5

# GUI settings
WINDOW_WIDTH: int = 400
WINDOW_HEIGHT: int = 500
DEFAULT_INFINITE_WAIT: bool = True

UI_TEMPLATES: dict = {
    "new_game": "new_game.png",
    "five_plus_two": "five_plus_two.png",
    "close": "close.png",
    "back": "back.png",
    "white_promotion_queen": "white_pawn_towards_queen.png",
    "black_promotion_queen": "black_pawn_towards_queen.png",
}

PIECE_VALUES: dict = {
    "pawn": 100,
    "knight": 300,
    "bishop": 320,
    "rook": 480,
    "queen": 900,
    "king": 20000,
}

LOG_LEVEL: str = "DEBUG"
SCREENSHOT_SCALE: float = 1.0

ENGINE_MAX_DEPTH: int = 8
ENGINE_TIME_LIMIT: float = 2.0
