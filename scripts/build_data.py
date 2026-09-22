"""Build machine-readable CSV/JSON, retrieval cards and SQLite from reviewed facts.

Only Python's standard library is required. Does not fetch or infer new facts.
"""
import csv
import json
import re
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads((ROOT / path).read_text())

def dump(path, value):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def table(path, rows):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows([{k: ('true' if v else 'false') if isinstance(v, bool) else v for k, v in r.items()} for r in rows])

def main():
    curated = read('data/curated_specs.json')
    business = read('data/synthetic_business.json')
    sources = {r['source_id']: r for r in read('data/source_manifest.json')}
    logs = {r['source_id']: r for r in read('data/raw/download_log.json')}
    pages = {sid: read('data/extracted/'+sid+'.json')['pages'] for sid in sources}
    version = curated['dataset_version']
    products, prices, evidence, runtime = [], [], [], []
    seen = set()
    for row in curated['products']:
        sid, sku = row['source_id'], row['sku']
        assert sku not in seen, f'Duplicate SKU {sku}'
        seen.add(sku)
        assert row['model'] in sources[sid]['models'], f'Wrong manual model {sku}'
        cover = re.sub(r'\s+', '', pages[sid][0]['text'])
        assert row['model'] in cover, f'Model not on manual cover: {sku}'
        for key in ('spec_page','connectivity_page','resolution_page'):
            assert 1 <= row[key] <= len(pages[sid]), f'Bad page {sku}/{key}'
        value = business['prices_cents'][sku]
        assert type(value) is int and value >= 0
        model = row['model']
        brand = row.get('brand') or sources[sid].get('publisher') or ('Dell' if sid.startswith('DELL-') else 'Unknown')
        p = {k: row[k] for k in ('sku','model','screen_inches','resolution','max_refresh_hz','usb_c_video','usb_c_pd_watts','usb_c_downstream_charge_watts')}
        p.update(brand=brand, name=brand+' '+model+' Monitor', category='monitor', unit='piece',
                 aliases='|'.join([model,brand+' '+model,sku]), video_inputs='|'.join(row['video_inputs']),
                 source_id=sid, source_url=sources[sid]['download_url'],
                 retrieved_at=logs[sid]['downloaded_at'], source_type='public_manufacturer_specification',
                 notes=row['notes'], dataset_version=version)
        products.append(p)
        price = dict(sku=sku,currency='SGD',unit_price_cents=value,price_version=business['rules']['price_version'],
                     effective_date=business['rules']['effective_date'],price_source_type='synthetic')
        prices.append(price)
        field_pages = {'model':1,'screen_inches':row['spec_page'],'resolution':row['resolution_page'],
                       'max_refresh_hz':row['resolution_page'],'usb_c_video':row['connectivity_page'],
                       'usb_c_pd_watts':row['connectivity_page'],
                       'usb_c_downstream_charge_watts':row['connectivity_page'],'video_inputs':row['connectivity_page']}
        this_evidence = []
        for field, page in field_pages.items():
            method = 'direct_specification'
            if field in ('usb_c_video','usb_c_pd_watts') and not row['usb_c_video']:
                method = 'normalized_from_exhaustive_connectivity_list_and_port_direction'
            if field == 'usb_c_downstream_charge_watts' and row[field] == 0:
                method = 'no_usb_connector_in_connectivity_list'
            if sid == 'DELL-P25HE' and field == 'usb_c_downstream_charge_watts':
                method = 'derived_5_volts_times_3_amps'
            e = dict(sku=sku,field=field,value=json.dumps(row[field],ensure_ascii=False),source_id=sid,
                     pdf_page=page,local_path=sources[sid]['local_path'],
                     source_url=sources[sid]['download_url']+'#page='+str(page),
                     method=method,review_status=row.get('review_status','assistant_checked_against_downloaded_manual'),
                     note=row['notes'] if 'usb_c' in field or field == 'max_refresh_hz' else '')
            evidence.append(e)
            this_evidence.append({**e,'value':row[field]})
        product = {**p,'aliases':p['aliases'].split('|'),'video_inputs':row['video_inputs'],
                   'price':price,'evidence':this_evidence,'stock_quantity':None,'delivery_lead_days':None}
        runtime.append(product)
    assert set(business['prices_cents']) == seen
    source_rows = []
    for sid,s in sources.items():
        publisher=s.get('publisher') or ('Dell' if sid.startswith('DELL-') else 'Unknown')
        source_rows.append(dict(source_id=sid,title=s['title'],models='|'.join(s['models']),
                                page_url=s['page_url'],download_url=s['download_url'],local_path=s['local_path'],
                                downloaded_at=logs[sid]['downloaded_at'],size_bytes=logs[sid]['size_bytes'],
                                page_count=len(pages[sid]),language='en',publisher=publisher,
                                rights=s.get('rights',f'Copyright {publisher}; public download, not an open-data licence. Preserve attribution; check redistribution terms.')))
    table('data/processed/products.csv',products)
    table('data/processed/prices.csv',prices)
    table('data/processed/sources.csv',source_rows)
    table('data/processed/field_evidence.csv',evidence)
    dump('data/processed/pricing_rules.json',business['rules'])
    dump('data/agent/catalog.json',dict(dataset_version=version,product_count=len(products),
         field_definitions=curated['fields'],rules=business['rules'],products=runtime))
    dump('dell_agent/data/agent/catalog.json',dict(dataset_version=version,product_count=len(products),
         field_definitions=curated['fields'],rules=business['rules'],products=runtime))
    dump('dell_agent/data/processed/pricing_rules.json',business['rules'])
    shutil.copy2(ROOT/'data/agent/tool_schemas.json',ROOT/'dell_agent/data/agent/tool_schemas.json')
    shutil.copy2(ROOT/'data/agent/instructions.md',ROOT/'dell_agent/data/agent/instructions.md')
    # Spec-only cards: retrieval must not become an alternative price engine.
    knowledge = ROOT/'data/agent/knowledge'
    knowledge.mkdir(parents=True,exist_ok=True)
    package_knowledge = ROOT/'dell_agent/data/agent/knowledge'
    package_knowledge.mkdir(parents=True,exist_ok=True)
    for directory in (knowledge, package_knowledge):
        for old_card in directory.glob('MON-*.md'):
            old_card.unlink()
    for p in runtime:
        card = '\n'.join([
            '# '+p['brand']+' '+p['model']+' ('+p['sku']+')','',
            'Source: official '+p['brand']+' specification. Specifications only; prices are provided by the pricing tool.',
            f"Viewable diagonal: {p['screen_inches']} inches.",
            f"Native resolution: {p['resolution']}. Maximum preset refresh: {p['max_refresh_hz']} Hz.",
            f"USB-C video input: {p['usb_c_video']}. Host power on video upstream port: {p['usb_c_pd_watts']} W.",
            f"USB-C downstream charging: {p['usb_c_downstream_charge_watts']} W (not a host video input).",
            'Video inputs: '+', '.join(p['video_inputs'])+'.',p['notes'],'',
            'Evidence: '+p['source_url'],
            'PDF pages: '+', '.join(map(str, sorted({e['pdf_page'] for e in p['evidence']})))+'.',
            'Stock, lead time, warranty and supplier availability are not supplied. Do not infer them.',''])
        for directory in (knowledge, package_knowledge):
            (directory/(p['sku']+'.md')).write_text(card)
    db_path = ROOT/'storage/catalog.sqlite'
    db_path.parent.mkdir(parents=True,exist_ok=True)
    # This database is a regenerable catalogue, never an application quote store.
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, model TEXT UNIQUE, payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS prices (sku TEXT, price_version TEXT, unit_price_cents INTEGER, currency TEXT, PRIMARY KEY(sku,price_version))')
        db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('DELETE FROM products')
        db.execute('DELETE FROM prices')
        for p in runtime:
            db.execute('INSERT INTO products VALUES (?,?,?)',(p['sku'],p['model'],json.dumps(p,ensure_ascii=False)))
            db.execute('INSERT INTO prices VALUES (?,?,?,?)',(p['sku'],p['price']['price_version'],p['price']['unit_price_cents'],'SGD'))
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('rules',json.dumps(business['rules'])))
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('dataset_version',json.dumps(version)))
    print(f'Built {len(products)} products, {len(prices)} synthetic prices, {len(evidence)} evidence rows, {len(sources)} source records, JSON and SQLite.')

if __name__ == '__main__':
    main()
