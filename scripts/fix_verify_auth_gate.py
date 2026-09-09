from pathlib import Path
import re
p = Path('scripts/verify_parallel_cli.sh')
text = p.read_text()
pat = re.compile(
    r'if \[\[ -z "\$\{PARALLEL_API_KEY:-\}" \]\]; then\n(?:.*\n)*?fi\n',
    re.M,
)
new = '''# Prefer PARALLEL_API_KEY. If unset, accept an active parallel-cli OAuth login.
if [[ -z "${PARALLEL_API_KEY:-}" ]]; then
  if ! parallel-cli auth 2>/dev/null | grep -q 'Active:'; then
    echo "No PARALLEL_API_KEY and parallel-cli is not authenticated. Export a key or run: parallel-cli login" >&2
    exit 3
  fi
  echo "PARALLEL_API_KEY unset; using parallel-cli stored OAuth credentials."
fi
'''
m = pat.search(text)
assert m, 'gate not found'
p.write_text(text[:m.start()] + new + text[m.end():])
print('fixed', p)
