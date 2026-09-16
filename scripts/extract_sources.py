"""Extract page-numbered source text. Requires pypdf; data build itself uses stdlib."""
import json
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]

def main():
    out = ROOT / 'data/extracted'
    out.mkdir(parents=True, exist_ok=True)
    for source in json.loads((ROOT / 'data/source_manifest.json').read_text()):
        reader = PdfReader(ROOT / source['local_path'])
        pages = [{'pdf_page': i+1, 'text': p.extract_text(extraction_mode='layout')} for i, p in enumerate(reader.pages)]
        result = {'source_id': source['source_id'], 'local_path': source['local_path'], 'page_count': len(pages), 'pages': pages}
        (out / (source['source_id']+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        (out / (source['source_id']+'.txt')).write_text('\n\n'.join(f"=== PDF page {p['pdf_page']} ===\n{p['text']}" for p in pages))
        print(source['source_id'], len(pages), 'pages')

if __name__ == '__main__':
    main()
