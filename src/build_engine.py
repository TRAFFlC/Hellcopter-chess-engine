"""
引擎编译脚本

该脚本负责编译 engine_core.c 为共享库，支持：
1. 参数化编译：从配置文件生成 engine_params.h
2. 增量编译：仅在源文件或参数变化时重新编译
3. 编译优化：支持 -O3, -march=native 等优化选项
4. 跨平台支持：Windows, Linux, macOS

使用方法:
    python build_engine.py                    # 使用默认参数编译
    python build_engine.py --config v1.0.0    # 使用指定配置编译
    python build_engine.py --force            # 强制重新编译
    python build_engine.py --no-optimize      # 禁用优化
    python build_engine.py clean              # 清理生成文件
"""

import os
import platform
import shutil
import subprocess
import sys
import json
import hashlib
import argparse
from pathlib import Path
from typing import Optional, Dict, Any


def _find_compiler_windows() -> tuple[str, list[str]] | None:
    """在 Windows 上查找可用的 C 编译器，返回 (编译器命令, 额外参数列表)。"""
    if shutil.which("gcc"):
        return "gcc", []
    if shutil.which("cl"):
        return "cl", []
    return None


def _find_compiler_unix() -> tuple[str, list[str]] | None:
    """在 Linux/Mac 上查找可用的 C 编译器。"""
    if shutil.which("gcc"):
        return "gcc", []
    if shutil.which("clang"):
        return "clang", []
    return None


def _load_config(config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径，如果为 None 则不加载配置

    Returns:
        配置字典，如果加载失败则返回 None
    """
    if config_path is None:
        return None

    # 如果只提供版本号，构建完整路径
    if not config_path.endswith('.json'):
        config_path = f"configs/{config_path}.json"

    config_file = Path(config_path)
    if not config_file.exists():
        print(f"警告: 配置文件不存在: {config_path}", file=sys.stderr)
        return None

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(
            f"已加载配置: {config.get('version', 'unknown')} - {config.get('description', '')}")
        return config
    except json.JSONDecodeError as e:
        print(f"错误: 配置文件格式不正确: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"错误: 无法读取配置文件: {e}", file=sys.stderr)
        return None


def _generate_params_header(config: Dict[str, Any], output_path: str) -> bool:
    """
    从配置生成 engine_params.h 头文件

    Args:
        config: 配置字典
        output_path: 输出文件路径

    Returns:
        是否成功生成
    """
    try:
        parameters = config.get("parameters", {})

        with open(output_path, 'w', encoding='utf-8') as f:
            # 写入文件头
            f.write(
                "/* ============================================================================\n")
            f.write(" * ENGINE_PARAMS.H - Chess Engine Parameter Definitions\n")
            f.write(
                " * ============================================================================\n")
            f.write(
                f" * Auto-generated from config version: {config.get('version', 'unknown')}\n")
            f.write(
                f" * Generated at: {config.get('created_at', 'unknown')}\n")
            f.write(f" * Description: {config.get('description', '')}\n")
            f.write(" * \n")
            f.write(
                " * DO NOT EDIT MANUALLY - Use the configuration management system to modify\n")
            f.write(" * parameters and regenerate this file.\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write("#ifndef ENGINE_PARAMS_H\n")
            f.write("#define ENGINE_PARAMS_H\n\n")

            # 棋子价值
            piece_values = parameters.get("piece_values", {})
            f.write(
                "/* ============================================================================\n")
            f.write(" * SECTION 1: PIECE VALUES\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write(f"#define PAWN_VALUE {piece_values.get('pawn', 100)}\n")
            f.write(
                f"#define KNIGHT_VALUE {piece_values.get('knight', 300)}\n")
            f.write(
                f"#define BISHOP_VALUE {piece_values.get('bishop', 320)}\n")
            f.write(f"#define ROOK_VALUE {piece_values.get('rook', 480)}\n")
            f.write(f"#define QUEEN_VALUE {piece_values.get('queen', 900)}\n")
            f.write(
                f"#define KING_VALUE {piece_values.get('king', 20000)}\n\n")

            # PST 表
            pst = parameters.get("pst", {})
            f.write(
                "/* ============================================================================\n")
            f.write(" * SECTION 2: PIECE-SQUARE TABLES (PST)\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")

            for table_name in ["mg_pawn", "eg_pawn", "mg_knight", "eg_knight",
                               "mg_bishop", "eg_bishop", "mg_rook", "eg_rook",
                               "mg_queen", "eg_queen", "mg_king", "eg_king"]:
                values = pst.get(table_name, [0] * 64)
                f.write(f"static const int {table_name}[64] = {{\n")
                for i in range(0, 64, 8):
                    row = ", ".join(f"{v:4d}" for v in values[i:i+8])
                    f.write(f"    {row},\n")
                f.write("};\n\n")

            # 评估权重
            eval_weights = parameters.get("eval_weights", {})
            f.write(
                "/* ============================================================================\n")
            f.write(" * SECTION 3: EVALUATION WEIGHTS\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write(
                f"#define BISHOP_PAIR_BONUS {eval_weights.get('bishop_pair_bonus', 50)}\n")
            f.write(
                f"#define DOUBLED_PAWN_PENALTY {eval_weights.get('doubled_pawn_penalty', -10)}\n")
            f.write(
                f"#define ISOLATED_PAWN_PENALTY {eval_weights.get('isolated_pawn_penalty', -20)}\n")
            f.write(
                f"#define PAWN_CHAIN_BONUS {eval_weights.get('pawn_chain_bonus', 15)}\n\n")
            f.write(
                f"#define SIMPLIFY_THRESHOLD {eval_weights.get('simplify_threshold', 200)}\n")
            f.write(
                f"#define SIMPLIFY_BONUS {eval_weights.get('simplify_bonus', 15)}\n\n")

            # 通路兵奖励
            passed_pawn_bonus = eval_weights.get(
                'passed_pawn_bonus', [0, 10, 20, 30, 50, 80, 120, 0])
            f.write("static const int passed_pawn_bonus[8] = {\n")
            f.write("    " + ", ".join(str(v)
                    for v in passed_pawn_bonus) + "\n")
            f.write("};\n\n")

            f.write(
                f"#define OPEN_FILE_BONUS {eval_weights.get('open_file_bonus', 15)}\n")
            f.write(
                f"#define SEMI_OPEN_FILE_BONUS {eval_weights.get('semi_open_file_bonus', 10)}\n")
            f.write(
                f"#define ROOK_POTENTIAL_OPEN_FILE {eval_weights.get('rook_potential_open_file', 8)}\n")
            f.write(
                f"#define ROOK_POTENTIAL_SEMI_OPEN {eval_weights.get('rook_potential_semi_open', 4)}\n")
            f.write(
                f"#define ROOK_ON_7TH_MG_BONUS {eval_weights.get('rook_7th_mg_bonus', 20)}\n")
            f.write(
                f"#define ROOK_ON_7TH_EG_BONUS {eval_weights.get('rook_7th_eg_bonus', 30)}\n")
            f.write(
                f"#define ROOK_ON_7TH_DOUBLE_BONUS {eval_weights.get('rook_7th_double_bonus', 20)}\n")
            f.write(
                f"#define ROOK_ON_7TH_KING_RANK8_BONUS {eval_weights.get('rook_7th_king_rank8_bonus', 25)}\n")
            f.write(
                f"#define ROOK_ON_7TH_DOUBLE_KING_RANK8_BONUS {eval_weights.get('rook_7th_double_king_rank8_bonus', 15)}\n")
            f.write(
                f"#define BISHOP_MOBILITY_BONUS {eval_weights.get('bishop_mobility_bonus', 15)}\n")
            f.write(
                f"#define BISHOP_BAD_PENALTY {eval_weights.get('bishop_bad_penalty', -15)}\n")
            f.write(
                f"#define QUEEN_CENTRALIZATION_MG {eval_weights.get('queen_centralization_mg', 15)}\n")
            f.write(
                f"#define QUEEN_CENTRALIZATION_EG {eval_weights.get('queen_centralization_eg', 0)}\n")
            f.write(
                f"#define CASTLE_SHORT_BONUS {eval_weights.get('castle_short_bonus', 30)}\n")
            f.write(
                f"#define CASTLE_LONG_BONUS {eval_weights.get('castle_long_bonus', 15)}\n")
            f.write(f"#define TEMPO_MG {eval_weights.get('tempo_mg', 15)}\n")
            f.write(f"#define TEMPO_EG {eval_weights.get('tempo_eg', 8)}\n\n")

            # 通路兵详细参数
            f.write("/* --- Passed Pawn Detail --- */\n")
            f.write(
                f"#define PASSED_PAWN_EG_WEIGHT {eval_weights.get('passed_pawn_eg_weight', 2)}\n")
            f.write(
                f"#define PASSED_PAWN_EG_PHASE_DENOM {eval_weights.get('passed_pawn_eg_phase_denom', 24)}\n")
            f.write(
                f"#define PROMO_THREAT_RANK6_BASE {eval_weights.get('promo_threat_rank6_base', 200)}\n")
            f.write(
                f"#define PROMO_THREAT_RANK5_BASE {eval_weights.get('promo_threat_rank5_base', 80)}\n")
            f.write(
                f"#define PROMO_THREAT_EG_DIVISOR {eval_weights.get('promo_threat_eg_divisor', 150)}\n")
            f.write(
                f"#define PASSED_PAWN_SUPPORTED_BONUS {eval_weights.get('passed_pawn_supported_bonus', 15)}\n")
            f.write(
                f"#define PASSED_PAWN_BLOCKED_BASE {eval_weights.get('passed_pawn_blocked_base', -10)}\n")
            f.write(
                f"#define PASSED_PAWN_BLOCKED_RANK_SCALE {eval_weights.get('passed_pawn_blocked_rank_scale', 5)}\n")
            f.write(
                f"#define PASSED_PAWN_BLOCKED_RANK_DENOM {eval_weights.get('passed_pawn_blocked_rank_denom', 3)}\n")
            f.write(
                f"#define PASSED_PAWN_CLEAR_PATH_BASE {eval_weights.get('passed_pawn_clear_path_base', 15)}\n")
            f.write(
                f"#define PASSED_PAWN_CLEAR_PATH_RANK_SCALE {eval_weights.get('passed_pawn_clear_path_rank_scale', 8)}\n")
            f.write(
                f"#define PASSED_PAWN_KING_DIST_BASE {eval_weights.get('passed_pawn_king_dist_base', 15)}\n")
            f.write(
                f"#define PASSED_PAWN_KING_DIST_SCALE {eval_weights.get('passed_pawn_king_dist_scale', 5)}\n")
            f.write(
                f"#define CENTER_PAWN_MG_BONUS {eval_weights.get('center_pawn_mg_bonus', 20)}\n")
            f.write(
                f"#define CONNECTED_PASSER_BONUS {eval_weights.get('connected_passer_bonus', 30)}\n")
            f.write(
                f"#define PAWN_CHAIN_LATERAL_BONUS {eval_weights.get('pawn_chain_lateral_bonus', 15)}\n")
            f.write(
                f"#define CENTER_PAWN_PAIR_BONUS {eval_weights.get('center_pawn_pair_bonus', 20)}\n\n")

            # 兵结构参数
            f.write("/* --- Pawn Structure --- */\n")
            f.write(
                f"#define ISOLATED_OPEN_FILE_MUL_NUM {eval_weights.get('isolated_open_file_multiplier_num', 3)}\n")
            f.write(
                f"#define ISOLATED_OPEN_FILE_MUL_DEN {eval_weights.get('isolated_open_file_multiplier_den', 2)}\n")
            f.write(
                f"#define BACKWARD_PAWN_PENALTY {eval_weights.get('backward_pawn_penalty', -15)}\n\n")

            # 中心控制
            f.write("/* --- Center Control --- */\n")
            f.write(
                f"#define CENTER_CONTROL_PIECE_BONUS {eval_weights.get('center_control_piece_bonus', 8)}\n")
            f.write(
                f"#define CENTER_CONTROL_EXTENDED_BONUS {eval_weights.get('center_control_extended_bonus', 3)}\n")
            f.write(
                f"#define CENTER_CONTROL_PAWN_BONUS {eval_weights.get('center_control_pawn_bonus', 20)}\n")
            f.write(
                f"#define CENTER_CONTROL_PAWN_EXTENDED_BONUS {eval_weights.get('center_control_pawn_extended_bonus', 6)}\n\n")

            # 悬空棋子/被攻击
            f.write("/* --- Hanging/Attacked Pieces --- */\n")
            f.write(
                f"#define HANGING_QUEEN_PENALTY {eval_weights.get('hanging_queen_penalty', 45)}\n")
            f.write(
                f"#define HANGING_ROOK_PENALTY {eval_weights.get('hanging_rook_penalty', 30)}\n")
            f.write(
                f"#define HANGING_MINOR_PENALTY {eval_weights.get('hanging_minor_penalty', 23)}\n")
            f.write(
                f"#define IN_CHECK_PENALTY {eval_weights.get('in_check_penalty', 25)}\n")
            f.write(
                f"#define BACK_RANK_MATE_PENALTY {eval_weights.get('back_rank_mate_penalty', -50)}\n")
            f.write(
                f"#define BACK_RANK_TRIPLE_PENALTY {eval_weights.get('back_rank_triple_penalty', -25)}\n\n")

            # 马位置/前哨站
            f.write("/* --- Knight Position/Outpost --- */\n")
            f.write(
                f"#define KNIGHT_EDGE_PENALTY {eval_weights.get('knight_edge_penalty', -30)}\n")
            f.write(
                f"#define KNIGHT_INITIAL_BLOCK_PENALTY {eval_weights.get('knight_initial_block_penalty', -25)}\n")
            f.write(
                f"#define OUTPOST_MG_BASE {eval_weights.get('outpost_mg_base', 15)}\n")
            f.write(
                f"#define OUTPOST_MG_RANK_SCALE {eval_weights.get('outpost_mg_rank_scale', 5)}\n")
            f.write(
                f"#define OUTPOST_EG_BASE {eval_weights.get('outpost_eg_base', 10)}\n")
            f.write(
                f"#define OUTPOST_EG_RANK_SCALE {eval_weights.get('outpost_eg_rank_scale', 3)}\n\n")

            # 被兵/马攻击
            f.write("/* --- Attacked by Pawn/Knight --- */\n")
            f.write(
                f"#define QUEEN_ATTACKED_BY_PAWN_PENALTY {eval_weights.get('queen_attacked_by_pawn_penalty', -25)}\n")
            f.write(
                f"#define ROOK_ATTACKED_BY_PAWN_PENALTY {eval_weights.get('rook_attacked_by_pawn_penalty', -20)}\n")
            f.write(
                f"#define MINOR_ATTACKED_BY_PAWN_PENALTY {eval_weights.get('minor_attacked_by_pawn_penalty', -15)}\n")
            f.write(
                f"#define QUEEN_ATTACKED_BY_PAWN_EXTRA {eval_weights.get('queen_attacked_by_pawn_extra', -5)}\n")
            f.write(
                f"#define ROOK_ATTACKED_BY_PAWN_EXTRA {eval_weights.get('rook_attacked_by_pawn_extra', -3)}\n")
            f.write(
                f"#define QUEEN_ATTACKED_BY_KNIGHT_PENALTY {eval_weights.get('queen_attacked_by_knight_penalty', -20)}\n")
            f.write(
                f"#define ROOK_ATTACKED_BY_KNIGHT_PENALTY {eval_weights.get('rook_attacked_by_knight_penalty', -15)}\n")
            f.write(
                f"#define MINOR_ATTACKED_BY_KNIGHT_PENALTY {eval_weights.get('minor_attacked_by_knight_penalty', -13)}\n")
            f.write(
                f"#define PIECE_DEFENDED_BY_PAWN_BONUS {eval_weights.get('piece_defended_by_pawn_bonus', 10)}\n\n")

            # 叉击/威胁
            f.write("/* --- Fork/Threat --- */\n")
            f.write(
                f"#define KNIGHT_FORK_QUEEN_ROOK_PENALTY {eval_weights.get('knight_fork_queen_rook_penalty', -75)}\n")
            f.write(
                f"#define KNIGHT_FORK_KING_PENALTY {eval_weights.get('knight_fork_king_penalty', -60)}\n")
            f.write(
                f"#define QUEEN_ATTACKED_BY_MINOR_UNDEFENDED {eval_weights.get('queen_attacked_by_minor_undefended', -75)}\n")
            f.write(
                f"#define QUEEN_ATTACKED_BY_MINOR_DEFENDED {eval_weights.get('queen_attacked_by_minor_defended', -30)}\n")
            f.write(
                f"#define ROOK_ATTACKED_BY_MINOR_UNDEFENDED {eval_weights.get('rook_attacked_by_minor_undefended', -40)}\n")
            f.write(
                f"#define ROOK_ATTACKED_BY_MINOR_DEFENDED {eval_weights.get('rook_attacked_by_minor_defended', -15)}\n")
            f.write(
                f"#define MINOR_ATTACKED_BY_MINOR_UNDEFENDED {eval_weights.get('minor_attacked_by_minor_undefended', -45)}\n")
            f.write(
                f"#define MINOR_ATTACKED_BY_MINOR_DEFENDED {eval_weights.get('minor_attacked_by_minor_defended', -18)}\n")
            f.write(
                f"#define PIECE_ATTACKED_BY_ROOK_UNDEFENDED {eval_weights.get('piece_attacked_by_rook_undefended', -20)}\n")
            f.write(
                f"#define PIECE_ATTACKED_BY_ROOK_DEFENDED {eval_weights.get('piece_attacked_by_rook_defended', -8)}\n")
            f.write(
                f"#define PIECE_ATTACKED_BY_BISHOP_UNDEFENDED {eval_weights.get('piece_attacked_by_bishop_undefended', -15)}\n")
            f.write(
                f"#define PIECE_ATTACKED_BY_BISHOP_DEFENDED {eval_weights.get('piece_attacked_by_bishop_defended', -6)}\n\n")

            # 开局发展
            f.write("/* --- Opening Development --- */\n")
            f.write(
                f"#define OPENING_KNIGHT_NOT_DEVELOPED_PENALTY {eval_weights.get('opening_knight_not_developed_penalty', -20)}\n")
            f.write(
                f"#define OPENING_BISHOP_NOT_DEVELOPED_PENALTY {eval_weights.get('opening_bishop_not_developed_penalty', -20)}\n")
            f.write(
                f"#define OPENING_EARLY_QUEEN_BASE {eval_weights.get('opening_early_queen_base', 40)}\n")
            f.write(
                f"#define OPENING_EARLY_QUEEN_SCALE {eval_weights.get('opening_early_queen_scale', 10)}\n")
            f.write(
                f"#define OPENING_EARLY_QUEEN_MIN {eval_weights.get('opening_early_queen_min', 10)}\n")
            f.write(
                f"#define OPENING_UNDEVELOPED_PENALTY_5 {eval_weights.get('opening_undeveloped_penalty_5', -30)}\n")
            f.write(
                f"#define OPENING_UNDEVELOPED_PENALTY_8 {eval_weights.get('opening_undeveloped_penalty_8', -20)}\n")
            f.write(
                f"#define OPENING_KING_NOT_CASTLED_PENALTY {eval_weights.get('opening_king_not_castled_penalty', -25)}\n")
            f.write(
                f"#define OPENING_EARLY_QUEEN_ADVANCE_BASE {eval_weights.get('opening_early_queen_advance_base', 50)}\n")
            f.write(
                f"#define OPENING_EARLY_QUEEN_ADVANCE_SCALE {eval_weights.get('opening_early_queen_advance_scale', 10)}\n")
            f.write(
                f"#define OPENING_EARLY_QUEEN_ADVANCE_MIN {eval_weights.get('opening_early_queen_advance_min', 20)}\n")
            f.write(
                f"#define OPENING_EARLY_ROOK_ADVANCE_PENALTY {eval_weights.get('opening_early_rook_advance_penalty', -15)}\n")
            f.write(
                f"#define OPENING_CENTER_PAWN_CONTROL_BONUS {eval_weights.get('opening_center_pawn_control_bonus', 10)}\n")
            f.write(
                f"#define OPENING_NO_CENTER_PAWN_PENALTY {eval_weights.get('opening_no_center_pawn_penalty', -35)}\n\n")

            # 不平衡
            f.write("/* --- Imbalance --- */\n")
            f.write(
                f"#define IMBALANCE_MG_BASE {eval_weights.get('imbalance_mg_base', 50)}\n")
            f.write(
                f"#define IMBALANCE_MG_SCALE {eval_weights.get('imbalance_mg_scale', 15)}\n")
            f.write(
                f"#define IMBALANCE_EG_SCALE {eval_weights.get('imbalance_eg_scale', 20)}\n")
            f.write(
                f"#define NO_MINOR_VS_TWO_MINOR_PENALTY {eval_weights.get('no_minor_vs_two_minor_penalty', 80)}\n")
            f.write(
                f"#define FIFTY_MOVE_URGENCY_DIVISOR {eval_weights.get('fifty_move_urgency_divisor', 200)}\n\n")

            # Mop-up
            f.write("/* --- Mop-up --- */\n")
            f.write(
                f"#define MOPUP_MATERIAL_THRESHOLD {eval_weights.get('mopup_material_threshold', 500)}\n")
            f.write(
                f"#define MOPUP_WINNING_KING_ACTIVITY_WEIGHT {eval_weights.get('mopup_winning_king_activity_weight', 15)}\n")
            f.write(
                f"#define MOPUP_LOSING_KING_ACTIVITY_WEIGHT {eval_weights.get('mopup_losing_king_activity_weight', 3)}\n")
            f.write(
                f"#define MOPUP_KING_ACTIVITY_EARLY_PHASE {eval_weights.get('mopup_king_activity_early_phase_threshold', 8)}\n")
            f.write(
                f"#define MOPUP_KING_ACTIVITY_EARLY_WEIGHT {eval_weights.get('mopup_king_activity_early_weight', 25)}\n")
            f.write(
                f"#define MOPUP_EDGE_WEIGHT {eval_weights.get('mopup_edge_weight', 120)}\n")
            f.write(
                f"#define MOPUP_PROXIMITY_WEIGHT {eval_weights.get('mopup_proximity_weight', 60)}\n")
            f.write(
                f"#define MOPUP_OPPOSITION_WEIGHT {eval_weights.get('mopup_opposition_weight', 80)}\n")
            f.write(
                f"#define MOPUP_GENERIC_EDGE_SCALE {eval_weights.get('mopup_generic_edge_scale', 80)}\n")
            f.write(
                f"#define MOPUP_GENERIC_PROXIMITY_SCALE {eval_weights.get('mopup_generic_proximity_scale', 50)}\n")
            f.write(
                f"#define KRK_ROOK_CUTOFF_BONUS {eval_weights.get('krk_rook_cutoff_bonus', 60)}\n")
            f.write(
                f"#define KRK_ROOK_FAR_PENALTY {eval_weights.get('krk_rook_far_penalty', -40)}\n")
            f.write(
                f"#define KQKR_CORNER_SCALE {eval_weights.get('kqkr_corner_scale', 150)}\n")
            f.write(
                f"#define KQKR_PROXIMITY_SCALE {eval_weights.get('kqkr_proximity_scale', 80)}\n")
            f.write(
                f"#define KQKR_QUEEN_PROXIMITY_SCALE {eval_weights.get('kqkr_queen_proximity_scale', 50)}\n")
            f.write(
                f"#define KQKR_STALEMATE_AVOID_PENALTY {eval_weights.get('kqkr_stalemate_avoid_penalty', -100)}\n")
            f.write(
                f"#define KQKR_CORNER_MATE_BONUS {eval_weights.get('kqkr_corner_mate_bonus', 200)}\n")
            f.write(
                f"#define KBNK_CORNER_SCALE {eval_weights.get('kbnk_corner_scale', 100)}\n")
            f.write(
                f"#define KBNK_PROXIMITY_SCALE {eval_weights.get('kbnk_proximity_scale', 60)}\n")
            f.write(
                f"#define KBNK_CORRECT_CORNER_BONUS {eval_weights.get('kbnk_correct_corner_bonus', 300)}\n")
            f.write(
                f"#define EXTENDED_MOPUP_EDGE_SCALE {eval_weights.get('extended_mopup_edge_scale', 80)}\n")
            f.write(
                f"#define EXTENDED_MOPUP_PROXIMITY_SCALE {eval_weights.get('extended_mopup_proximity_scale', 40)}\n\n")

            # 残局特殊
            f.write("/* --- Endgame Special --- */\n")
            f.write(
                f"#define OPPOSITE_BISHOP_DRAW_FACTOR_NO_PAWN {eval_weights.get('opposite_bishop_draw_factor_no_pawn', 8)}\n")
            f.write(
                f"#define OPPOSITE_BISHOP_DRAW_FACTOR_PAWN {eval_weights.get('opposite_bishop_draw_factor_pawn', 12)}\n")
            f.write(
                f"#define OPPOSITE_BISHOP_DRAW_DIVISOR {eval_weights.get('opposite_bishop_draw_divisor', 16)}\n")
            f.write(
                f"#define ANTI_SIMPLIFY_PER_PIECE_SCALE {eval_weights.get('anti_simplify_per_piece_scale', 2)}\n")
            f.write(
                f"#define ANTI_SIMPLIFY_PIECE_THRESHOLD {eval_weights.get('anti_simplify_piece_threshold', 6)}\n\n")

            # 搜索参数
            search_params = parameters.get("search_params", {})
            f.write(
                "/* ============================================================================\n")
            f.write(
                " * SECTION 4: SEARCH PARAMETERS\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write(
                f"#define NULL_MOVE_REDUCTION {search_params.get('null_move_reduction', 2)}\n")
            f.write(
                f"#define NULL_MOVE_MIN_DEPTH {search_params.get('null_move_min_depth', 3)}\n")
            f.write(
                f"#define NULL_MOVE_VERIFICATION_DEPTH {search_params.get('null_move_verification_depth', 6)}\n")
            f.write(
                f"#define NULL_MOVE_VERIFICATION_REDUCTION {search_params.get('null_move_verification_reduction', 5)}\n\n")

            f.write(
                f"#define LMR_ENABLED {1 if search_params.get('lmr_enabled', False) else 0}\n")
            f.write(
                f"#define LMR_MIN_DEPTH {search_params.get('lmr_min_depth', 3)}\n")
            f.write(
                f"#define LMR_MOVE_THRESHOLD {search_params.get('lmr_move_threshold', 2)}\n")
            f.write(
                f"#define LMR_BASE {search_params.get('lmr_base', 0.75)}\n")
            f.write(
                f"#define LMR_DIVISOR {search_params.get('lmr_divisor', 2.25)}\n")
            f.write(
                f"#define LMR_HISTORY_THRESHOLD {search_params.get('lmr_history_threshold', 500)}\n\n")

            f.write(
                f"#define FUTILITY_ENABLED {1 if search_params.get('futility_enabled', False) else 0}\n")
            f.write(
                f"#define FUTILITY_MARGIN_BASE {search_params.get('futility_margin_base', 150)}\n\n")

            f.write(
                f"#define RAZORING_ENABLED {1 if search_params.get('razoring_enabled', False) else 0}\n")
            f.write(
                f"#define RAZORING_MARGIN {search_params.get('razoring_margin', 300)}\n\n")

            f.write(
                f"#define QS_MAX_DEPTH_MG {search_params.get('qs_max_depth_mg', 8)}\n")
            f.write(
                f"#define QS_MAX_DEPTH_EG {search_params.get('qs_max_depth_eg', 16)}\n\n")

            # 搜索排序/剪枝参数
            f.write("/* --- Move Ordering & Pruning --- */\n")
            f.write(
                f"#define SEE_KING_VALUE {search_params.get('see_king_value', 10000)}\n")
            f.write(
                f"#define MVV_LVA_SCALE {search_params.get('mvv_lva_scale', 10)}\n")
            f.write(
                f"#define QS_TT_MOVE_SCORE {search_params.get('qs_tt_move_score', 100000)}\n")
            f.write(
                f"#define QS_DELTA_MARGIN {search_params.get('qs_delta_margin', 200)}\n")
            f.write(
                f"#define QS_CHECK_MAX_DEPTH {search_params.get('qs_check_max_depth', 2)}\n")
            f.write(
                f"#define QS_CHECK_SCORE {search_params.get('qs_check_score', 5000)}\n")
            f.write(
                f"#define LAZY_EVAL_THRESHOLD {search_params.get('lazy_eval_threshold', 2000)}\n")
            f.write(
                f"#define TT_MOVE_SCORE {search_params.get('tt_move_score', 2000000)}\n")
            f.write(
                f"#define GOOD_CAPTURE_BASE {search_params.get('good_capture_base', 1000000)}\n")
            f.write(
                f"#define BAD_CAPTURE_BASE {search_params.get('bad_capture_base', 200000)}\n")
            f.write(
                f"#define KILLER_BASE_SCORE {search_params.get('killer_base_score', 40000)}\n")
            f.write(
                f"#define KILLER_STEP {search_params.get('killer_step', 1000)}\n")
            f.write(
                f"#define COUNTERMOVE_SCORE {search_params.get('countermove_score', 30000)}\n")
            f.write(
                f"#define FOLLOWUP_SCORE {search_params.get('followup_score', 25000)}\n")
            f.write(
                f"#define PROMOTION_SCORE {search_params.get('promotion_score', 50000)}\n")
            f.write(
                f"#define ENDGAME_PASSER_ADVANCE_SCALE {search_params.get('endgame_passer_advance_scale', 2000)}\n")
            f.write(
                f"#define BLUNDER_PENALTY {search_params.get('blunder_penalty', -5000)}\n")
            f.write(
                f"#define BLUNDER_BONUS {search_params.get('blunder_bonus', 5000)}\n\n")

            # RFP 参数
            f.write("/* --- Reverse Futility Pruning --- */\n")
            f.write(
                f"#define RFP_DEPTH_SQ_SCALE {search_params.get('rfp_depth_sq_scale', 20)}\n")
            f.write(
                f"#define RFP_DEPTH_SCALE {search_params.get('rfp_depth_scale', 40)}\n")
            f.write(f"#define RFP_CAP {search_params.get('rfp_cap', 800)}\n")
            f.write(
                f"#define RFP_IMPROVING_NUM {search_params.get('rfp_improving_num', 3)}\n")
            f.write(
                f"#define RFP_IMPROVING_DEN {search_params.get('rfp_improving_den', 4)}\n")
            f.write(
                f"#define RFP_LOW_PHASE_NUM {search_params.get('rfp_low_phase_num', 3)}\n")
            f.write(
                f"#define RFP_LOW_PHASE_DEN {search_params.get('rfp_low_phase_den', 4)}\n\n")

            # NMP 参数
            f.write("/* --- Null Move Pruning --- */\n")
            f.write(
                f"#define NMP_BASE_REDUCTION {search_params.get('nmp_base_reduction', 3)}\n")
            f.write(
                f"#define NMP_DEPTH_DIVISOR {search_params.get('nmp_depth_divisor', 6)}\n")
            f.write(
                f"#define NMP_HIGH_EVAL_THRESHOLD {search_params.get('nmp_high_eval_threshold', 200)}\n")
            f.write(
                f"#define NMP_HIGH_EVAL_EXTRA_REDUCTION {search_params.get('nmp_high_eval_extra_reduction', 1)}\n")
            f.write(
                f"#define NMP_BIG_ADV_THRESHOLD {search_params.get('nmp_big_adv_threshold', 2000)}\n")
            f.write(
                f"#define NMP_BIG_ADV_REDUCTION {search_params.get('nmp_big_adv_reduction', -2)}\n")
            f.write(
                f"#define NMP_MED_ADV_THRESHOLD {search_params.get('nmp_med_adv_threshold', 1000)}\n")
            f.write(
                f"#define NMP_MED_ADV_REDUCTION {search_params.get('nmp_med_adv_reduction', -1)}\n")
            f.write(
                f"#define NMP_LOW_PHASE_THRESHOLD {search_params.get('nmp_low_phase_threshold', 10)}\n")
            f.write(
                f"#define NMP_LOW_PHASE_REDUCTION {search_params.get('nmp_low_phase_reduction', -1)}\n\n")

            # 其他搜索参数
            f.write("/* --- Other Search --- */\n")
            f.write(
                f"#define SEE_PRUNE_DEPTH_SCALE {search_params.get('see_prune_depth_scale', 120)}\n")
            f.write(
                f"#define HISTORY_PRUNE_BASE {search_params.get('history_prune_base', 3)}\n")
            f.write(f"#define LMP_BASE {search_params.get('lmp_base', 6)}\n")
            f.write(
                f"#define SE_BETA_DEPTH_SCALE {search_params.get('se_beta_depth_scale', 2)}\n")
            f.write(
                f"#define HISTORY_SCORE_LIMIT {search_params.get('history_score_limit', 8000)}\n")
            f.write(
                f"#define HISTORY_UPDATE_SCALE {search_params.get('history_update_scale', 1)}\n\n")

            # 常量
            constants = parameters.get("constants", {})
            f.write(
                "/* ============================================================================\n")
            f.write(
                " * SECTION 5: CONSTANTS\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write(
                f"#define MATE_SCORE {constants.get('mate_score', 900000)}\n")
            f.write(f"#define DELTA {constants.get('delta', 900)}\n")
            f.write(
                f"#define INF_SCORE {constants.get('inf_score', 1000000)}\n")
            f.write(
                f"#define PAWN_HASH_SIZE_EXP {constants.get('pawn_hash_size_exp', 18)}\n")
            f.write(
                f"#define MAX_BLUNDER_ENTRIES {constants.get('max_blunder_entries', 10000)}\n\n")

            f.write(
                "/* ============================================================================\n")
            f.write(
                " * SECTION 5.5: ENDGAME PARAMETERS\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write(
                f"#define ENDGAME_PHASE_THRESHOLD {constants.get('endgame_phase_threshold', 6)}\n")
            f.write(
                f"#define ENDGAME_DEPTH_BONUS {constants.get('endgame_depth_bonus', 0)}\n")
            f.write(
                f"#define ENDGAME_NMR_BONUS {constants.get('endgame_nmr_bonus', 1)}\n")
            f.write(
                f"#define KING_ACTIVITY_WEIGHT {constants.get('king_activity_weight', 10)}\n")
            f.write(
                f"#define CLEARLY_WINNING_THRESHOLD {constants.get('clearly_winning_threshold', 2000)}\n")
            f.write(
                f"#define FUTILITY_WINNING_THRESHOLD {constants.get('futility_winning_threshold', 2000)}\n")
            f.write(
                f"#define FUTILITY_EG_MARGIN_NUM {constants.get('futility_eg_margin_num', 2)}\n")
            f.write(
                f"#define FUTILITY_EG_MARGIN_DEN {constants.get('futility_eg_margin_den', 3)}\n\n")

            # 机动性表
            mobility = parameters.get("mobility_tables", {})
            f.write(
                "/* ============================================================================\n")
            f.write(
                " * SECTION 5.6: MOBILITY TABLES\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")

            for table_name in ["knight_mob_mg", "knight_mob_eg",
                               "bishop_mob_mg", "bishop_mob_eg",
                               "rook_mob_mg", "rook_mob_eg",
                               "queen_mob_mg", "queen_mob_eg"]:
                values = mobility.get(table_name, [0] * 9)
                f.write(f"static const int {table_name}[{len(values)}] = {{\n")
                f.write("    " + ", ".join(str(v) for v in values) + "\n")
                f.write("};\n\n")

            # King Danger 表
            king_danger = parameters.get("king_danger", {})
            kd_table = king_danger.get("king_danger_table", [0] * 128)
            f.write(
                "/* ============================================================================\n")
            f.write(
                " * SECTION 5.7: KING DANGER TABLE\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write(f"static const int king_danger_table[128] = {{\n")
            for i in range(0, 128, 8):
                row = ", ".join(f"{v:5d}" for v in kd_table[i:i+8])
                f.write(f"    {row},\n")
            f.write("};\n\n")

            f.write(
                f"#define KING_DANGER_CAP {king_danger.get('king_danger_cap', 4000)}\n")
            f.write(
                f"#define KNIGHT_ATTACK_BASE {king_danger.get('knight_attack_base', 2)}\n")
            f.write(
                f"#define BISHOP_ATTACK_BASE {king_danger.get('bishop_attack_base', 2)}\n")
            f.write(
                f"#define ROOK_ATTACK_BASE {king_danger.get('rook_attack_base', 3)}\n")
            f.write(
                f"#define QUEEN_ATTACK_BASE {king_danger.get('queen_attack_base', 5)}\n")
            f.write(
                f"#define KNIGHT_ATTACK_PER_SQ {king_danger.get('knight_attack_per_sq', 1)}\n")
            f.write(
                f"#define BISHOP_ATTACK_PER_SQ {king_danger.get('bishop_attack_per_sq', 1)}\n")
            f.write(
                f"#define ROOK_ATTACK_PER_SQ {king_danger.get('rook_attack_per_sq', 2)}\n")
            f.write(
                f"#define QUEEN_ATTACK_PER_SQ {king_danger.get('queen_attack_per_sq', 2)}\n")
            f.write(
                f"#define PAWN_SHIELD_RANK2_PENALTY {king_danger.get('pawn_shield_rank2_penalty', 4)}\n")
            f.write(
                f"#define PAWN_SHIELD_NO_PAWN_PENALTY {king_danger.get('pawn_shield_no_pawn_penalty', 10)}\n")
            f.write(
                f"#define OPEN_FILE_KING_ZONE_PENALTY {king_danger.get('open_file_king_zone_penalty', 6)}\n")
            f.write(
                f"#define SEMI_OPEN_FILE_KING_ZONE_PENALTY {king_danger.get('semi_open_file_king_zone_penalty', 3)}\n")
            f.write(
                f"#define ATTACKER_COUNT_BONUS {king_danger.get('attacker_count_bonus', 6)}\n")
            f.write(
                f"#define KING_DANGER_EG_SCALE_BASE {king_danger.get('king_danger_eg_scale_base', 40)}\n")
            f.write(
                f"#define KING_DANGER_EG_SCALE_PHASE {king_danger.get('king_danger_eg_scale_phase', 40)}\n\n")

            # 时间管理参数
            time_mgmt = parameters.get("time_management", {})
            f.write(
                "/* ============================================================================\n")
            f.write(
                " * SECTION 5.8: TIME MANAGEMENT\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")

            est_moves = time_mgmt.get('est_moves_by_material', [
                                      35, 25, 22, 18, 15, 12])
            f.write(
                f"static const int EST_MOVES_BY_MATERIAL[{len(est_moves)}] = {{\n")
            f.write("    " + ", ".join(str(v) for v in est_moves) + "\n")
            f.write("};\n\n")

            est_thresholds = time_mgmt.get(
                'est_moves_material_thresholds', [4, 6, 10, 14, 20])
            f.write(
                f"static const int EST_MOVES_MATERIAL_THRESHOLDS[{len(est_thresholds)}] = {{\n")
            f.write("    " + ", ".join(str(v) for v in est_thresholds) + "\n")
            f.write("};\n\n")

            # 阶段感知时间分配常量
            f.write(f"#define PHASE_OPENING_MOVES_REMAINING {time_mgmt.get('phase_opening_moves_remaining', 20)}\n")
            f.write(f"#define PHASE_MIDGAME_MOVES_REMAINING {time_mgmt.get('phase_midgame_moves_remaining', 12)}\n")
            f.write(f"#define PHASE_ENDGAME_MOVES_REMAINING {time_mgmt.get('phase_endgame_moves_remaining', 20)}\n")
            f.write(f"#define PHASE_OPENING_MAX_MOVE {time_mgmt.get('phase_opening_max_move', 12)}\n")
            f.write(f"#define PHASE_MIDGAME_MAX_MOVE {time_mgmt.get('phase_midgame_max_move', 30)}\n")
            f.write(f"#define PHASE_BASE_MAX_TIME_FRACTION_NUM {time_mgmt.get('phase_base_max_time_fraction_num', 1)}\n")
            f.write(f"#define PHASE_BASE_MAX_TIME_FRACTION_DEN {time_mgmt.get('phase_base_max_time_fraction_den', 3)}\n\n")

            root_capture = time_mgmt.get('root_capture_value', [
                                         0, 100, 300, 320, 500, 900, 0])
            f.write(
                f"static const int ROOT_CAPTURE_VALUE[{len(root_capture)}] = {{\n")
            f.write("    " + ", ".join(str(v) for v in root_capture) + "\n")
            f.write("};\n\n")

            root_attacker = time_mgmt.get('root_attacker_value', [
                                          0, 10, 30, 30, 50, 90, 0])
            f.write(
                f"static const int ROOT_ATTACKER_VALUE[{len(root_attacker)}] = {{\n")
            f.write("    " + ", ".join(str(v) for v in root_attacker) + "\n")
            f.write("};\n\n")

            mat_depth_bonus = time_mgmt.get(
                'material_depth_bonus', [4, 3, 2, 1])
            f.write(
                f"static const int MATERIAL_DEPTH_BONUS[{len(mat_depth_bonus)}] = {{\n")
            f.write("    " + ", ".join(str(v) for v in mat_depth_bonus) + "\n")
            f.write("};\n\n")

            mat_depth_thresh = time_mgmt.get(
                'material_depth_thresholds', [4, 6, 10, 14])
            f.write(
                f"static const int MATERIAL_DEPTH_THRESHOLDS[{len(mat_depth_thresh)}] = {{\n")
            f.write("    " + ", ".join(str(v)
                    for v in mat_depth_thresh) + "\n")
            f.write("};\n\n")

            f.write(
                f"#define OPTIMAL_TIME_INC_FRACTION_NUM {time_mgmt.get('optimal_time_inc_fraction_num', 1)}\n")
            f.write(
                f"#define OPTIMAL_TIME_INC_FRACTION_DEN {time_mgmt.get('optimal_time_inc_fraction_den', 2)}\n")
            f.write(
                f"#define MAX_TIME_FRACTION_NUM {time_mgmt.get('max_time_fraction_num', 2)}\n")
            f.write(
                f"#define MAX_TIME_FRACTION_DEN {time_mgmt.get('max_time_fraction_den', 5)}\n")
            f.write(
                f"#define MAX_TIME_OPTIMAL_MULTIPLIER {time_mgmt.get('max_time_optimal_multiplier', 4)}\n")
            f.write(
                f"#define EXTREME_PRESSURE_FRACTION_NUM {time_mgmt.get('extreme_pressure_fraction_num', 2)}\n")
            f.write(
                f"#define EXTREME_PRESSURE_FRACTION_DEN {time_mgmt.get('extreme_pressure_fraction_den', 5)}\n")
            f.write(
                f"#define EXTREME_PRESSURE_INC_FRACTION_NUM {time_mgmt.get('extreme_pressure_inc_fraction_num', 4)}\n")
            f.write(
                f"#define EXTREME_PRESSURE_INC_FRACTION_DEN {time_mgmt.get('extreme_pressure_inc_fraction_den', 5)}\n")
            f.write(
                f"#define EXTREME_PRESSURE_SAFETY_MARGIN {time_mgmt.get('extreme_pressure_safety_margin', 50)}\n")
            f.write(
                f"#define MIN_OPTIMAL_TIME_MS {time_mgmt.get('min_optimal_time_ms', 10)}\n")
            f.write(
                f"#define TIME_CHECK_MASK_NORMAL {time_mgmt.get('time_check_mask_normal', 511)}\n")
            f.write(
                f"#define TIME_CHECK_MASK_LOW {time_mgmt.get('time_check_mask_low', 127)}\n")
            f.write(
                f"#define TIME_CHECK_MASK_VERY_LOW {time_mgmt.get('time_check_mask_very_low', 255)}\n")
            f.write(
                f"#define REPETITION_SCORE {time_mgmt.get('repetition_score', 200000)}\n")
            f.write(
                f"#define REPETITION_EVAL_THRESHOLD {time_mgmt.get('repetition_eval_threshold', 50)}\n")
            f.write(
                f"#define IN_CHECK_TIME_REDUCTION_NUM {time_mgmt.get('in_check_time_reduction_num', 17)}\n")
            f.write(
                f"#define IN_CHECK_TIME_REDUCTION_DEN {time_mgmt.get('in_check_time_reduction_den', 20)}\n")
            f.write(
                f"#define INITIAL_ASPIRATION_WINDOW {time_mgmt.get('initial_aspiration_window', 50)}\n")
            f.write(
                f"#define ASPIRATION_WINDOW_GROWTH_BASE {time_mgmt.get('aspiration_window_growth_base', 10)}\n")
            f.write(
                f"#define ASPIRATION_FULL_WINDOW_THRESHOLD {time_mgmt.get('aspiration_full_window_threshold', 500)}\n")
            f.write(
                f"#define HISTORY_DECAY_NUM {time_mgmt.get('history_decay_num', 9)}\n")
            f.write(
                f"#define HISTORY_DECAY_DEN {time_mgmt.get('history_decay_den', 10)}\n")
            f.write(
                f"#define NORMAL_ASPIRATION_WINDOW {time_mgmt.get('normal_aspiration_window', 25)}\n")
            f.write(
                f"#define EASY_MOVE_STABILITY_COUNT {time_mgmt.get('easy_move_stability_count', 3)}\n")
            f.write(
                f"#define EASY_MOVE_SCORE_THRESHOLD {time_mgmt.get('easy_move_score_threshold', 10)}\n")
            f.write(
                f"#define EASY_MOVE_TIME_FRACTION_NUM {time_mgmt.get('easy_move_time_fraction_num', 1)}\n")
            f.write(
                f"#define EASY_MOVE_TIME_FRACTION_DEN {time_mgmt.get('easy_move_time_fraction_den', 2)}\n")
            f.write(
                f"#define PANIC_SCORE_DROP_THRESHOLD {time_mgmt.get('panic_score_drop_threshold', 100)}\n")
            f.write(
                f"#define HARD_MOVE_SCORE_DROP_THRESHOLD {time_mgmt.get('hard_move_score_drop_threshold', 50)}\n")
            f.write(
                f"#define HARD_MOVE_TIME_MULTIPLIER_NUM {time_mgmt.get('hard_move_time_multiplier_num', 5)}\n")
            f.write(
                f"#define HARD_MOVE_TIME_MULTIPLIER_DEN {time_mgmt.get('hard_move_time_multiplier_den', 2)}\n")
            f.write(
                f"#define NORMAL_TIME_MULTIPLIER_NUM {time_mgmt.get('normal_time_multiplier_num', 11)}\n")
            f.write(
                f"#define NORMAL_TIME_MULTIPLIER_DEN {time_mgmt.get('normal_time_multiplier_den', 10)}\n")
            f.write(
                f"#define SAFETY_CAP_REMAINING_FRACTION_NUM {time_mgmt.get('safety_cap_remaining_fraction_num', 1)}\n")
            f.write(
                f"#define SAFETY_CAP_REMAINING_FRACTION_DEN {time_mgmt.get('safety_cap_remaining_fraction_den', 4)}\n")
            f.write(
                f"#define SAFETY_CAP_INC_FRACTION_NUM {time_mgmt.get('safety_cap_inc_fraction_num', 1)}\n")
            f.write(
                f"#define SAFETY_CAP_INC_FRACTION_DEN {time_mgmt.get('safety_cap_inc_fraction_den', 2)}\n")
            f.write(
                f"#define SAFETY_CAP_MIN_TIME_MS {time_mgmt.get('safety_cap_min_time_ms', 50)}\n")
            f.write(
                f"#define SMP_DEPTH_OFFSET_BASE {time_mgmt.get('smp_depth_offset_base', 1)}\n")
            f.write(
                f"#define SMP_DEPTH_OFFSET_MOD {time_mgmt.get('smp_depth_offset_mod', 4)}\n")
            f.write(
                f"#define SMP_ASPIRATION_WINDOW {time_mgmt.get('smp_aspiration_window', 50)}\n")
            f.write(
                f"#define SMP_WINDOW_RETRY_MULTIPLIER {time_mgmt.get('smp_window_retry_multiplier', 4)}\n")
            f.write(
                f"#define SMP_TIME_CHECK_FRACTION_NUM {time_mgmt.get('smp_time_check_fraction_num', 7)}\n")
            f.write(
                f"#define SMP_TIME_CHECK_FRACTION_DEN {time_mgmt.get('smp_time_check_fraction_den', 10)}\n\n")

            # 多线程
            threading = parameters.get("threading", {})
            f.write(
                "/* ============================================================================\n")
            f.write(" * SECTION 6: THREADING\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write(
                f"#define THREADING_ENABLED {1 if threading.get('enabled', False) else 0}\n")
            f.write(
                f"#define NUM_THREADS {threading.get('num_threads', 1)}\n\n")

            # 参数验证
            f.write(
                "/* ============================================================================\n")
            f.write(" * PARAMETER VALIDATION MACROS\n")
            f.write(
                " * ============================================================================\n")
            f.write(" */\n\n")
            f.write(
                "#if PAWN_VALUE <= 0 || KNIGHT_VALUE <= 0 || BISHOP_VALUE <= 0 || \\\n")
            f.write("    ROOK_VALUE <= 0 || QUEEN_VALUE <= 0 || KING_VALUE <= 0\n")
            f.write('#error "Piece values must be positive"\n')
            f.write("#endif\n\n")
            f.write("#if NUM_THREADS < 1 || NUM_THREADS > 64\n")
            f.write('#error "NUM_THREADS must be between 1 and 64"\n')
            f.write("#endif\n\n")
            f.write("#if NULL_MOVE_MIN_DEPTH < 1 || LMR_MIN_DEPTH < 1\n")
            f.write('#error "Minimum depth parameters must be at least 1"\n')
            f.write("#endif\n\n")

            f.write("#endif /* ENGINE_PARAMS_H */\n")

        print(f"已生成参数头文件: {output_path}")
        return True
    except Exception as e:
        print(f"错误: 生成头文件失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def _compute_file_hash(file_path: str) -> str:
    """
    计算文件的 MD5 哈希值

    Args:
        file_path: 文件路径

    Returns:
        MD5 哈希值（十六进制字符串）
    """
    md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
        return md5.hexdigest()
    except Exception:
        return ""


def _needs_rebuild(src_file: str, output_file: str, params_header: str) -> bool:
    """
    检查是否需要重新编译

    Args:
        src_file: 源文件路径
        output_file: 输出文件路径
        params_header: 参数头文件路径

    Returns:
        是否需要重新编译
    """
    # 如果输出文件不存在，需要编译
    if not os.path.exists(output_file):
        print("输出文件不存在，需要编译")
        return True

    # 获取文件修改时间
    output_mtime = os.path.getmtime(output_file)
    src_mtime = os.path.getmtime(src_file)

    # 如果源文件更新，需要编译
    if src_mtime > output_mtime:
        print("源文件已更新，需要重新编译")
        return True

    # 如果参数头文件更新，需要编译
    if os.path.exists(params_header):
        params_mtime = os.path.getmtime(params_header)
        if params_mtime > output_mtime:
            print("参数头文件已更新，需要重新编译")
            return True

    # 检查 fathom/tbprobe.c 是否更新
    script_dir = os.path.dirname(os.path.abspath(src_file))
    fathom_src = os.path.join(script_dir, "fathom", "src", "tbprobe.c")
    if os.path.exists(fathom_src):
        fathom_mtime = os.path.getmtime(fathom_src)
        if fathom_mtime > output_mtime:
            print("fathom/tbprobe.c 已更新，需要重新编译")
            return True

    print("无需重新编译（使用增量编译）")
    return False


def build(config_path: Optional[str] = None, force: bool = False, optimize: bool = True, pgo: bool = False) -> bool:
    """
    检测平台并编译 engine_core.c 为共享库。

    Args:
        config_path: 配置文件路径或版本号（如 "v1.0.0"），如果为 None 则使用现有的 engine_params.h
        force: 是否强制重新编译
        optimize: 是否启用编译优化

    Returns:
        True 表示编译成功，False 表示失败。
    """
    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    src_file = os.path.join(script_dir, "engine_core.c")
    params_header = os.path.join(script_dir, "engine_params.h")
    fathom_src = os.path.join(script_dir, "fathom", "src", "tbprobe.c")
    fathom_inc = os.path.join(script_dir, "fathom", "src")

    if not os.path.exists(src_file):
        print(f"错误: 源文件未找到: {src_file}", file=sys.stderr)
        return False

    # 如果提供了配置文件，生成参数头文件
    if config_path:
        config = _load_config(config_path)
        if config is None:
            print("错误: 无法加载配置文件", file=sys.stderr)
            return False

        if not _generate_params_header(config, params_header):
            print("错误: 无法生成参数头文件", file=sys.stderr)
            return False
    else:
        # 检查参数头文件是否存在
        if not os.path.exists(params_header):
            print(f"警告: 参数头文件不存在: {params_header}", file=sys.stderr)
            print("将使用默认参数编译", file=sys.stderr)

    # 确定输出文件（输出到项目根目录，供 Python 层加载）
    output_dir = os.path.dirname(script_dir)
    if system == "Windows":
        output_file = os.path.join(output_dir, "engine_core.dll")
    elif system == "Linux":
        output_file = os.path.join(output_dir, "engine_core.so")
    elif system == "Darwin":
        output_file = os.path.join(output_dir, "engine_core.dylib")
    else:
        print(f"错误: 不支持的操作系统: {system}", file=sys.stderr)
        return False

    # 检查是否需要重新编译
    if not force and not _needs_rebuild(src_file, output_file, params_header):
        print(f"编译已是最新: {output_file}")
        return True

    # 查找编译器
    if system == "Windows":
        compiler_info = _find_compiler_windows()
        if compiler_info is None:
            print(
                "错误: 未找到可用的 C 编译器。"
                "请安装 MinGW-w64 (gcc) 或 Microsoft Visual C++ (cl) 并将其加入 PATH。",
                file=sys.stderr,
            )
            return False

        compiler, _ = compiler_info

        if compiler == "gcc":
            cmd = [
                "gcc",
                "-shared",
                "-std=c99",
                f"-I{fathom_inc}",
                "-o", output_file,
                src_file,
                fathom_src,
                "-lm",
            ]

            # 添加优化选项
            if optimize:
                cmd.insert(2, "-O3")
                cmd.insert(3, "-march=native")
                cmd.insert(4, "-fomit-frame-pointer")
                cmd.insert(5, "-DNDEBUG")

            if pgo and compiler == "gcc":
                pgo_gen = os.path.join(script_dir, "Hellcopter_pgo_gen.exe")
                cmd_gen = list(cmd)
                cmd_gen[cmd_gen.index("-fomit-frame-pointer")
                        ] = "-fprofile-generate"
                cmd_gen[cmd_gen.index(output_file)] = pgo_gen
                print(f"\nPGO Pass 1: 编译 profile 生成版本...")
                print(f"执行命令: {' '.join(cmd_gen)}")
                r1 = subprocess.run(
                    cmd_gen, capture_output=True, text=True, cwd=script_dir)
                if r1.returncode != 0:
                    print("PGO Pass 1 编译失败！", file=sys.stderr)
                    if r1.stderr:
                        print(r1.stderr, file=sys.stderr)
                    return False
                print(f"PGO Pass 1 成功，运行 bench 收集 profile...")
                bench_proc = subprocess.run(
                    [pgo_gen],
                    input="bench\nquit\n",
                    capture_output=True, text=True, timeout=600, cwd=script_dir
                )
                print(
                    bench_proc.stdout[-500:] if len(bench_proc.stdout) > 500 else bench_proc.stdout)
                gcda_dir = script_dir
                gcda_count = len([f for f in os.listdir(
                    gcda_dir) if f.endswith('.gcda')])
                print(f"收集到 {gcda_count} 个 .gcda 文件")
                cmd_use = list(cmd)
                idx = cmd_use.index("-fomit-frame-pointer")
                cmd_use[idx] = "-fprofile-use"
                cmd_use.insert(idx + 1, "-Wno-error=missing-profile")
                cmd = cmd_use
                print(f"\nPGO Pass 2: 使用 profile 重新编译...")
                print(f"执行命令: {' '.join(cmd)}")
                # LTO 在某些 MinGW 版本上可能有问题，暂时禁用
                # cmd.insert(4, "-flto")
        else:  # cl
            obj_file = os.path.join(script_dir, "engine_core.obj")
            cmd = [
                "cl",
                "/LD",
                f"/Fe{output_file}",
                f"/Fo{obj_file}",
                src_file,
                fathom_src,
                f"/I{fathom_inc}",
            ]

            # 添加优化选项
            if optimize:
                cmd.insert(1, "/O2")
                cmd.insert(2, "/GL")
                cmd.insert(3, "/DNDEBUG")

    elif system == "Linux":
        compiler_info = _find_compiler_unix()
        if compiler_info is None:
            print(
                "错误: 未找到可用的 C 编译器。请安装 gcc 或 clang。",
                file=sys.stderr,
            )
            return False

        compiler, _ = compiler_info
        cmd = [
            compiler,
            "-shared",
            "-std=c99",
            "-fPIC",
            f"-I{fathom_inc}",
            "-o", output_file,
            src_file,
            fathom_src,
            "-lm",
        ]

        # 添加优化选项
        if optimize:
            cmd.insert(3, "-O3")
            cmd.insert(4, "-march=native")
            cmd.insert(5, "-fomit-frame-pointer")
            cmd.insert(6, "-DNDEBUG")
            # LTO 可选
            # cmd.insert(5, "-flto")

    elif system == "Darwin":
        compiler_info = _find_compiler_unix()
        if compiler_info is None:
            print(
                "错误: 未找到可用的 C 编译器。请安装 gcc 或 clang (Xcode Command Line Tools)。",
                file=sys.stderr,
            )
            return False

        compiler, _ = compiler_info
        cmd = [
            compiler,
            "-dynamiclib",
            "-std=c99",
            f"-I{fathom_inc}",
            "-o", output_file,
            src_file,
            fathom_src,
        ]

        # 添加优化选项
        if optimize:
            cmd.insert(2, "-O3")
            cmd.insert(3, "-march=native")
            cmd.insert(4, "-flto")
            cmd.insert(5, "-fomit-frame-pointer")
            cmd.insert(6, "-DNDEBUG")

    print(f"\n{'='*60}")
    print(f"检测到平台: {system}")
    print(f"使用编译器: {compiler}")
    print(f"优化选项: {'启用' if optimize else '禁用'}")
    print(f"输出文件: {output_file}")
    print(f"执行命令: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd, capture_output=True,
                            text=True, cwd=script_dir)

    if result.returncode != 0:
        print("编译失败！", file=sys.stderr)
        if result.stdout:
            print("stdout:\n" + result.stdout, file=sys.stderr)
        if result.stderr:
            print("stderr:\n" + result.stderr, file=sys.stderr)
        return False

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        print(f"\n{'='*60}")
        print(f"[SUCCESS] 编译成功: {output_file}")
        print(f"  文件大小: {file_size:,} 字节")
        print(f"{'='*60}\n")
        return True
    else:
        print("错误: 编译命令返回 0，但输出文件未生成。", file=sys.stderr)
        return False


def build_exe(config_path: Optional[str] = None, force: bool = False, optimize: bool = True, pgo: bool = False) -> bool:
    """
    编译 uci_main.c 和 engine_core.c 为独立的 UCI 可执行文件。
    pgo=True 时执行 PGO 两遍编译。
    """
    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    engine_src = os.path.join(script_dir, "engine_core.c")
    uci_src = os.path.join(script_dir, "uci_main.c")
    params_header = os.path.join(script_dir, "engine_params.h")
    fathom_src = os.path.join(script_dir, "fathom", "src", "tbprobe.c")
    fathom_inc = os.path.join(script_dir, "fathom", "src")

    if not os.path.exists(engine_src):
        print(f"错误: 源文件未找到: {engine_src}", file=sys.stderr)
        return False
    if not os.path.exists(uci_src):
        print(f"错误: 源文件未找到: {uci_src}", file=sys.stderr)
        return False

    if config_path:
        config = _load_config(config_path)
        if config is None:
            print("错误: 无法加载配置文件", file=sys.stderr)
            return False
        if not _generate_params_header(config, params_header):
            print("错误: 无法生成参数头文件", file=sys.stderr)
            return False

    output_dir = os.path.dirname(script_dir)
    dist_dir = os.path.join(output_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    if system == "Windows":
        output_file = os.path.join(dist_dir, "Hellcopter.exe")
    else:
        output_file = os.path.join(dist_dir, "Hellcopter")

    if not force and not _needs_rebuild(engine_src, output_file, params_header):
        if not _needs_rebuild(uci_src, output_file, params_header):
            print(f"编译已是最新: {output_file}")
            return True

    if system == "Windows":
        compiler_info = _find_compiler_windows()
        if compiler_info is None:
            print("错误: 未找到可用的 C 编译器。", file=sys.stderr)
            return False

        compiler, _ = compiler_info
        if compiler == "gcc":
            cmd = [
                "gcc", "-std=c99",
                f"-I{fathom_inc}",
                "-o", output_file,
                engine_src, uci_src, fathom_src,
                "-lm",
            ]
            if optimize:
                cmd.insert(2, "-O3")
                cmd.insert(3, "-march=native")
                cmd.insert(4, "-fomit-frame-pointer")
                cmd.insert(5, "-DNDEBUG")

            if pgo and compiler == "gcc":
                pgo_gen = os.path.join(dist_dir, "Hellcopter_pgo_gen.exe")
                cmd_gen = list(cmd)
                cmd_gen[cmd_gen.index("-fomit-frame-pointer")
                        ] = "-fprofile-generate"
                cmd_gen[cmd_gen.index(output_file)] = pgo_gen
                print(f"\nPGO Pass 1: 编译 profile 生成版本...")
                print(f"执行命令: {' '.join(cmd_gen)}")
                r1 = subprocess.run(
                    cmd_gen, capture_output=True, text=True, cwd=script_dir)
                if r1.returncode != 0:
                    print("PGO Pass 1 编译失败！", file=sys.stderr)
                    if r1.stderr:
                        print(r1.stderr, file=sys.stderr)
                    return False
                print(f"PGO Pass 1 成功，运行 bench 收集 profile...")
                bench_proc = subprocess.run(
                    [pgo_gen],
                    input="bench\nquit\n",
                    capture_output=True, text=True, timeout=600, cwd=dist_dir
                )
                print(
                    bench_proc.stdout[-500:] if len(bench_proc.stdout) > 500 else bench_proc.stdout)
                for f in os.listdir(dist_dir):
                    if f.startswith("Hellcopter_pgo_gen-") and f.endswith(('.gcda', '.gcno')):
                        new_name = f.replace(
                            "Hellcopter_pgo_gen-", "Hellcopter-")
                        src = os.path.join(dist_dir, f)
                        dst = os.path.join(dist_dir, new_name)
                        if os.path.exists(dst):
                            os.remove(dst)
                        os.rename(src, dst)
                gcda_count = len([f for f in os.listdir(dist_dir) if f.startswith(
                    "Hellcopter-") and f.endswith('.gcda')])
                print(f"收集到 {gcda_count} 个 .gcda 文件")
                cmd_use = list(cmd)
                idx = cmd_use.index("-fomit-frame-pointer")
                cmd_use[idx] = "-fprofile-use"
                cmd = cmd_use
                print(f"\nPGO Pass 2: 使用 profile 重新编译...")
                print(f"执行命令: {' '.join(cmd)}")
        else:
            obj_engine = os.path.join(script_dir, "engine_core.obj")
            obj_uci = os.path.join(script_dir, "uci_main.obj")
            cmd = [
                "cl",
                f"/Fe{output_file}",
                f"/Fo{obj_engine}",
                engine_src, uci_src,
            ]
            if optimize:
                cmd.insert(1, "/O2")
                cmd.insert(2, "/GL")
                cmd.insert(3, "/DNDEBUG")
    elif system in ("Linux", "Darwin"):
        compiler_info = _find_compiler_unix()
        if compiler_info is None:
            print("错误: 未找到可用的 C 编译器。", file=sys.stderr)
            return False

        compiler, _ = compiler_info
        cmd = [
            compiler, "-std=c99",
            "-o", output_file,
            engine_src, uci_src,
            "-lm", "-lpthread",
        ]
        if optimize:
            cmd.insert(2, "-O3")
            cmd.insert(3, "-march=native")
            cmd.insert(4, "-fomit-frame-pointer")
            cmd.insert(5, "-DNDEBUG")
    else:
        print(f"错误: 不支持的操作系统: {system}", file=sys.stderr)
        return False

    print(f"\n{'='*60}")
    print(f"编译 UCI 可执行文件")
    print(f"检测到平台: {system}")
    print(f"使用编译器: {compiler}")
    print(f"优化选项: {'启用' if optimize else '禁用'}")
    print(f"输出文件: {output_file}")
    print(f"执行命令: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd, capture_output=True,
                            text=True, cwd=script_dir)

    if result.returncode != 0:
        print("编译失败！", file=sys.stderr)
        if result.stdout:
            print("stdout:\n" + result.stdout, file=sys.stderr)
        if result.stderr:
            print("stderr:\n" + result.stderr, file=sys.stderr)
        return False

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        book_src = os.path.join(script_dir, "dist", "Goi5.1.bin")
        if os.path.exists(book_src):
            print(f"  开局库已存在: {book_src}")
        else:
            print("  提示: dist/Goi5.1.bin 不存在，开局库将不可用")
        print(f"\n{'='*60}")
        print(f"[SUCCESS] 编译成功: {output_file}")
        print(f"  文件大小: {file_size:,} 字节 ({file_size / 1024:.1f} KB)")
        print(f"{'='*60}\n")
        return True
    else:
        print("错误: 编译命令返回 0，但输出文件未生成。", file=sys.stderr)
        return False


def clean():
    """删除生成的共享库和中间文件。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    files_to_remove = [
        "engine_core.dll",
        "engine_core.so",
        "engine_core.dylib",
        "engine_core.obj",
        "engine_core.o",
        "libengine_core.a",
    ]

    print("清理生成文件...")
    removed_count = 0
    for name in files_to_remove:
        for d in (root_dir, script_dir):
            path = os.path.join(d, name)
            if os.path.exists(path):
                os.remove(path)
                print(f"  已删除: {d}\\{name}")
                removed_count += 1

    if removed_count == 0:
        print("  没有需要清理的文件")
    else:
        print(f"已清理 {removed_count} 个文件")


def main():
    """主函数，处理命令行参数"""
    parser = argparse.ArgumentParser(
        description="编译 hellcopter 国际象棋引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python build_engine.py                    # 使用默认参数编译共享库
  python build_engine.py exe                # 编译为独立 UCI 可执行文件
  python build_engine.py --config v1.0.0    # 使用指定配置编译
  python build_engine.py --force            # 强制重新编译
  python build_engine.py --no-optimize      # 禁用优化
  python build_engine.py clean              # 清理生成文件
        """
    )

    parser.add_argument(
        'action',
        nargs='?',
        default='build',
        choices=['build', 'exe', 'clean'],
        help='执行的操作：build（编译共享库）、exe（编译可执行文件）或 clean（清理）'
    )

    parser.add_argument(
        '--config', '-c',
        type=str,
        default="v1.9.0",
        help='配置文件路径或版本号（如 v1.0.0）'
    )

    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='强制重新编译，忽略增量编译检查'
    )

    parser.add_argument(
        '--no-optimize',
        action='store_true',
        help='禁用编译优化（用于调试）'
    )

    parser.add_argument(
        '--pgo',
        action='store_true',
        help='启用 PGO (Profile-Guided Optimization) 两遍编译'
    )

    args = parser.parse_args()

    if args.action == 'clean':
        clean()
        sys.exit(0)
    elif args.action == 'exe':
        success = build_exe(
            config_path=args.config,
            force=args.force,
            optimize=not args.no_optimize,
            pgo=args.pgo
        )
        sys.exit(0 if success else 1)
    else:
        success = build(
            config_path=args.config,
            force=args.force,
            optimize=not args.no_optimize
        )
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
