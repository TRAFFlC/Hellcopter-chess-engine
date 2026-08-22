"""Test: run engine through cutechess and capture the actual UCI conversation."""
import subprocess, sys, os, tempfile, json, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import load_and_resolve_config

# Create ASCII-only temp dir
ascii_temp = os.path.join(base_dir, "__trace_test__")
os.makedirs(ascii_temp, exist_ok=True)

# Create adapter scripts
for label, cfg in [("trace_a", "tuning/texel_tuned.json"), ("trace_b", "engine_params.json")]:
    tmp = os.path.join(ascii_temp, label)
    os.makedirs(tmp, exist_ok=True)
    resolved = load_and_resolve_config(os.path.join(base_dir, cfg))
    dest_params = os.path.join(tmp, "engine_params.json")
    with open(dest_params, "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2)
    
    # Create adapter that TRACES all UCI I/O
    script = os.path.join(tmp, "uci_adapter.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write("import os, sys\n")
        f.write('os.environ["ENGINE_PARAMS"] = "%s"\n' % dest_params.replace("\\", "/"))
        f.write('sys.path.insert(0, "%s")\n' % base_dir.replace("\\", "/"))
        f.write("from uci_engine import UCIEngine\n")
        f.write("import sys\n")
        # Monkey-patch UCIEngine to trace all I/O
        f.write("orig_run = UCIEngine.run\n")
        f.write("def traced_run(self):\n")
        f.write("    self.send = lambda msg: (print('UCI_OUT:', msg, file=sys.stderr, flush=True) if 'bestmove' in msg or 'info' in msg else None, print(msg, flush=True))\n")
        f.write("    # Trace input\n")
        f.write("    import threading\n")
        f.write("    orig = self.send\n")
        f.write("    self.send = lambda msg: (None, print(msg, flush=True))[1]\n")
        f.write("    def read_input():\n")
        f.write("        for line in sys.stdin:\n")
        f.write("            print('UCI_IN:', line.rstrip(), file=sys.stderr, flush=True)\n")
        f.write("            orig_handle = self.handle_line\n")
        f.write("            self.handle_line(line.rstrip())\n")
        f.write("        sys.exit(0)\n")
        f.write("    t = threading.Thread(target=read_input, daemon=True)\n")
        f.write("    t.start()\n")
        f.write("    t.join()\n")
        f.write("UCIEngine.run = traced_run\n")
        f.write("u = UCIEngine()\n")
        # Don't call u.run() - our traced version will intercept
        f.write("import sys\n")
        # Actually just let the original run work, but trace stdin too
        f.write("if __name__ == '__main__':\n")
        f.write("    u = UCIEngine()\n")
        f.write("    # Override send to trace\n")
        f.write("    original_send = u.send\n")
        f.write("    u.send = lambda msg: (print('ENG:', msg, file=sys.stderr, flush=True), original_send(msg))[-1]\n")
        f.write("    u.orig_handle_line = u.handle_line\n")
        f.write("    def traced_handle(line):\n")
        f.write("        print('UCI<<:', repr(line), file=sys.stderr, flush=True)\n")
        f.write("        return u.orig_handle_line(line)\n")
        f.write("    u.handle_line = traced_handle\n")
        f.write("    u.run()\n")

# Run match
cmd = [
    os.path.join(base_dir, "cutechess-1.3.1-win64", "cutechess-cli.exe"),
    "-engine", "name=TA", "proto=uci",
    f"cmd={sys.executable}", f"arg={os.path.join(ascii_temp, 'trace_a', 'uci_adapter.py')}",
    f"dir={os.path.join(ascii_temp, 'trace_a')}",
    "-engine", "name=TB", "proto=uci",
    f"cmd={sys.executable}", f"arg={os.path.join(ascii_temp, 'trace_b', 'uci_adapter.py')}",
    f"dir={os.path.join(ascii_temp, 'trace_b')}",
    "-each", "tc=10+0.1",
    "-rounds", "1",
]
print("Running:", " ".join(cmd), file=sys.stderr, flush=True)
result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
# Show errors (our trace goes to stderr)
print("=== STDERR (trace) ===", file=sys.stderr, flush=True)
print(result.stderr[:3000], file=sys.stderr, flush=True)
print("=== STDOUT (match) ===", file=sys.stderr, flush=True)
print(result.stdout[:1000], file=sys.stderr, flush=True)
shutil.rmtree(ascii_temp, ignore_errors=True)
