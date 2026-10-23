"""Render an existing source PDF page without editing it; no external service."""
from pathlib import Path
import base64, json, sys
import fitz

path = Path(sys.argv[1])
requested = int(sys.argv[2])
with fitz.open(path) as doc:
    if requested < 1 or requested > len(doc):
        raise ValueError(f'Page must be between 1 and {len(doc)}')
    page = doc[requested-1]
    image = page.get_pixmap(matrix=fitz.Matrix(1.65,1.65),alpha=False).tobytes('png')
    print(json.dumps({'page':requested,'pages':len(doc),'pdfText':page.get_text(),
                      'pageImage':'data:image/png;base64,'+base64.b64encode(image).decode('ascii')},ensure_ascii=False))
