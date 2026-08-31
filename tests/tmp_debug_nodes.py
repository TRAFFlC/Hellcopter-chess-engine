import engine_wrapper as ew
import ctypes

ew.init()

# Test 1: Direct call with node_limit=100
nodes = ctypes.c_int(0)
m = ew._lib.find_best_move_c(
    b'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
    ctypes.c_double(3600.0),
    ctypes.c_double(0),
    ctypes.c_double(0),
    ctypes.c_int(0),
    ctypes.c_int(0),
    ctypes.c_int(100),
    ctypes.c_longlong(100),
    ctypes.byref(nodes),
    None,
    ctypes.c_int(0),
)
f = m.from_sq & 7
r = m.from_sq >> 3
t = m.to_sq & 7
tr = m.to_sq >> 3
uci = chr(97 + f) + str(r) + chr(97 + t) + str(tr)
print("Test1 node_limit=100: " + uci + ", nodes=" + str(nodes.value))

# Test 2: search() wrapper with node_limit=200
uci2, nodes2 = ew.search('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', 3600.0, 100, node_limit=200)
print("Test2 node_limit=200: " + uci2 + ", nodes=" + str(nodes2))

# Test 3: search() with node_limit=0 (no limit)
uci3, nodes3 = ew.search('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', 0.1, 8, node_limit=0)
print("Test3 node_limit=0: " + uci3 + ", nodes=" + str(nodes3))
