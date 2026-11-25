import json
import re
from pathlib import Path


def preview_html(course, assets):
    assets = Path(assets)
    html = (assets/'index.html').read_text(encoding='utf-8')
    css = (assets/'style.css').read_text(encoding='utf-8')
    js = (assets/'app.js').read_text(encoding='utf-8')
    safe = json.dumps(course, ensure_ascii=False).replace('<', r'\u003c')
    html = re.sub(r'<link rel="stylesheet" href="style\.css(?:\?[^"]*)?">', lambda _: '<style>'+css+'</style>', html)
    return re.sub(r'<script src="app\.js(?:\?[^"]*)?"></script>',
                  lambda _: '<script>window.VOCAB_PREVIEW='+safe+';</script><script>'+js+'</script>', html)
