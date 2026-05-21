import ctypes
import os
import sys

def analyze_move_scores():
    dll_path = os.path.join(os.path.dirname(__file__), "engine_core.dll")
    if not os.path.exists(dll_path):
        print(f"DLL not found: {dll_path}")
        return
    
    engine = ctypes.CDLL(dll_path)
    
    engine.get_root_move_scores.argtypes = [
        ctypes.c_char_p, ctypes.c_double, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
    ]
    engine.get_root_move_scores.restype = None
    
    fen = b"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    
    scores = (ctypes.c_int * 256)()
    from_sqs = (ctypes.c_int * 256)()
    to_sqs = (ctypes.c_int * 256)()
    count = ctypes.c_int()
    
    engine.get_root_move_scores(fen, 1.0, 12, scores, from_sqs, to_sqs, ctypes.byref(count))
    
    move_list = []
    for i in range(count.value):
        move_list.append({
            'from': from_sqs[i],
            'to': to_sqs[i],
            'score': scores[i]
        })
    
    move_list.sort(key=lambda x: -x['score'])
    
    print("=" * 60)
    print("开局着法分数分析 (搜索深度 12, 时间 1s)")
    print("=" * 60)
    
    sq_names = 'a1b1c1d1e1f1g1h1a2b2c2d2e2f2g2h2a3b3c3d3e3f3g3h3a4b4c4d4e4f4g4h4a5b5c5d5e5f5g5h5a6b6c6d6e6f6g6h6a7b7c7d7e7f7g7h7a8b8c8d8e8f8g8h8'
    
    def sq_to_name(sq):
        return sq_names[sq*2:sq*2+2]
    
    def move_to_str(m):
        return f"{sq_to_name(m['from'])}{sq_to_name(m['to'])}"
    
    best_score = move_list[0]['score']
    
    print(f"\n最佳着法: {move_to_str(move_list[0])} 分数: {best_score}")
    print(f"\n所有着法分数分布:")
    print("-" * 40)
    
    exact_same_count = 0
    within_5_count = 0
    within_15_count = 0
    within_30_count = 0
    
    for i, m in enumerate(move_list):
        diff = best_score - m['score']
        if diff == 0 and i > 0:
            exact_same_count += 1
        if diff <= 5:
            within_5_count += 1
        if diff <= 15:
            within_15_count += 1
        if diff <= 30:
            within_30_count += 1
        
        if i < 20:
            print(f"{i+1:2d}. {move_to_str(m):5s} 分数: {m['score']:6d} (差距: {diff:4d})")
    
    print("-" * 40)
    print(f"\n统计:")
    print(f"  总着法数: {len(move_list)}")
    print(f"  与最佳分数完全相同: {exact_same_count} 个")
    print(f"  与最佳分数差距 <= 5: {within_5_count} 个")
    print(f"  与最佳分数差距 <= 15: {within_15_count} 个")
    print(f"  与最佳分数差距 <= 30: {within_30_count} 个")
    
    print(f"\n分析:")
    if exact_same_count > 0:
        print(f"  ⚠️ 有 {exact_same_count} 个着法与最佳着法分数完全相同!")
    if within_15_count > 1:
        print(f"  ⚠️ 有 {within_15_count} 个着法在 perturbation 阈值(15)范围内!")
        print(f"     这意味着 perturbation 可能从这些着法中随机选择")
    
    return move_list

if __name__ == "__main__":
    analyze_move_scores()
