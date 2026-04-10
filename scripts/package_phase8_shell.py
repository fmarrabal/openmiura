from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
out = root / 'reports' / 'phase8_package_manifest.json'
out.write_text(json.dumps({'ok': True, 'generated_from': str(root), 'targets': ['desktop','mobile']}, indent=2), encoding='utf-8')
print(out)
