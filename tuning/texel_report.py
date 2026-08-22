import json
d = json.load(open('tuning/texel_log.json'))
print(f'K = {d.get("K", "?")}')
print(f'Iters: {len(d["history"])}')
print()
for h in d['history']:
    print('  iter %3d: loss=%.6f  |grad|=%.6f  [%.0fs]' % (h['iter'], h['loss'], h['grad_norm'], h['time_s']))
print()
print('Initial loss: %.6f' % d['history'][0]['loss'])
print('Final loss:   %.6f' % d['history'][-1]['loss'])
gain = d['history'][0]['loss'] - d['history'][-1]['loss']
print('Gain:         %+.6f (%.2f%%)' % (gain, gain / d['history'][0]['loss'] * 100))
print()
if 'params' in d:
    print('Final params:')
    for k, v in sorted(d['params'].items()):
        print('  %s: %s' % (k, v))
