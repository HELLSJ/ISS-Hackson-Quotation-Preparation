"""Download only the official PDFs in the manifest; preserve existing files."""
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

def main():
    sources = json.loads((ROOT / 'data/source_manifest.json').read_text())
    record_path = ROOT / 'data/raw/download_log.json'
    previous = {x['source_id']: x for x in json.loads(record_path.read_text())} if record_path.exists() else {}
    records = []
    for source in sources:
        path = ROOT / source['local_path']
        if path.exists() and path.read_bytes().startswith(b'%PDF-'):
            record = previous.get(source['source_id'])
            if record is None:
                raise RuntimeError(f"Existing file lacks download provenance: {path}")
            record = dict(record, **source)
            print('Existing:', path.name, flush=True)
        else:
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; QuotationAgentData/2.0)'}
            if 'psref.lenovo.com' in source['download_url']:
                headers['Referer'] = 'https://psref.lenovo.com/'
            req = Request(source['download_url'], headers=headers)
            with urlopen(req, timeout=60) as response:
                data = response.read()
                if not data.startswith(b'%PDF-'):
                    raise ValueError(f"Not a PDF: {source['source_id']}")
                record = dict(source, downloaded_at=datetime.now(timezone.utc).isoformat(),
                              final_url=response.url, size_bytes=len(data), content_type=response.headers.get('Content-Type'))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print('Downloaded:', path.name, len(data), 'bytes', flush=True)
        records.append(record)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        # Keep records from a previous partial run until all downloads complete.
        previous[record['source_id']] = record
        record_path.write_text(json.dumps(list(previous.values()), ensure_ascii=False, indent=2)+'\n')
    record_path.write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n')

if __name__ == '__main__':
    main()
