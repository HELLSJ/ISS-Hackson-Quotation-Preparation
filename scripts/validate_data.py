"""Validate data relationships and run the small offline tools test suite."""
import csv
import io
import json
import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def read(path): return json.loads((ROOT/path).read_text())
def rows(path):
    with (ROOT/path).open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))

def human_review_status(dataset_version):
    path=ROOT/'reports/evaluation/data-freeze-review-signed.csv'
    if not path.is_file():
        return 'NOT PERFORMED: independent data-freeze review record is missing.'
    review=rows('reports/evaluation/data-freeze-review-signed.csv')
    passed=[r for r in review if r['dataset_version']==dataset_version and r['independent_human_result']=='PASS']
    if len(review)==24 and len(passed)==24:
        reviewers=sorted({r['reviewer'] for r in passed if r['reviewer']})
        dates=sorted({r['reviewed_at'] for r in passed if r['reviewed_at']})
        if len(reviewers)==1 and len(dates)==1:
            return (f'PASSED: 24/24 independent evidence checks signed by {reviewers[0]} '
                    f'on {dates[0]}; see reports/evaluation/data-freeze-review-signed.csv.')
    return 'NOT PASSED: independent data-freeze review is incomplete or inconsistent.'

def main():
    catalog=read('data/agent/catalog.json')
    curated=read('data/curated_specs.json')
    sources=read('data/source_manifest.json')
    log={r['source_id']:r for r in read('data/raw/download_log.json')}
    products=rows('data/processed/products.csv')
    prices=rows('data/processed/prices.csv')
    evidence=rows('data/processed/field_evidence.csv')
    skus={r['sku'] for r in products}
    expected_count=50
    assert len(skus)==len(products)==len(catalog['products'])==expected_count
    assert skus=={r['sku'] for r in prices}
    assert len({(r['sku'],r['price_version']) for r in prices})==len(prices)
    assert all(r['currency']=='SGD' and int(r['unit_price_cents'])>=0 and r['price_source_type']=='synthetic' for r in prices)
    assert len(evidence)==expected_count*8
    page_counts={}
    local_source_pdf_count=0
    for s in sources:
        f=ROOT/s['local_path']
        if f.is_file():
            assert f.read_bytes().startswith(b'%PDF-')
            assert f.stat().st_size==log[s['source_id']]['size_bytes']
            local_source_pdf_count+=1
        extracted=read('data/extracted/'+s['source_id']+'.json')
        page_counts[s['source_id']]=extracted['page_count']
        assert len(extracted['pages'])==extracted['page_count']
        assert s['download_url'].startswith(('https://dl.dell.com/','https://psref.lenovo.com/'))
    for e in evidence:
        assert e['sku'] in skus and e['source_id'] in page_counts
        assert 1<=int(e['pdf_page'])<=page_counts[e['source_id']]
        assert json.loads(e['value']) is not None
    for p in catalog['products']:
        assert type(p['usb_c_video']) is bool
        assert p['usb_c_pd_watts']>=0
        assert p['stock_quantity'] is None and p['delivery_lead_days'] is None
        assert len(p['evidence'])==8
        spec=next(r for r in curated['products'] if r['sku']==p['sku'])
        for field in curated['fields']: assert spec[field]==p[field]
    with sqlite3.connect(ROOT/'storage/catalog.sqlite') as db:
        actual={sku:json.loads(payload) for sku,payload in db.execute('SELECT sku,payload FROM products')}
        assert actual=={p['sku']:p for p in catalog['products']}
        assert db.execute('SELECT count(*) FROM prices').fetchone()[0]==expected_count
    counts={}
    ids=[]
    for split in ('dev','holdout'):
        cases=[json.loads(l) for l in (ROOT/f'data/evaluation/enquiries_{split}.jsonl').read_text().splitlines()]
        counts[split]=len(cases)
        assert len(cases)==20
        ids.extend(r['case_id'] for r in cases)
    answers=[json.loads(l) for l in (ROOT/'data/evaluation/expected_results.jsonl').read_text().splitlines()]
    assert len(ids)==len(set(ids))==40 and set(ids)=={r['case_id'] for r in answers}
    assert len(list((ROOT/'data/agent/knowledge').glob('MON-*.md')))==expected_count
    assert len(list((ROOT/'dell_agent/data/agent/knowledge').glob('MON-*.md')))==expected_count
    schemas=read('data/agent/tool_schemas.json')['tools']
    assert {r['function']['name'] for r in schemas}=={'get_product','search_products','calculate_quote'}
    for t in schemas:
        assert t['type']=='function' and t['function']['parameters']['type']=='object'
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(
        str(ROOT/'tests'), pattern='test_catalog_tools.py'
    )
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report=dict(checked_at=datetime.now(timezone.utc).isoformat(),dataset_version=catalog['dataset_version'],
                source_document_count=len(sources),source_page_count=sum(page_counts.values()),
                source_pdfs_in_submission=0,local_source_pdf_count=local_source_pdf_count,
                source_bytes_at_freeze=sum(r['size_bytes'] for r in log.values()),products=len(products),
                synthetic_prices=len(prices),field_evidence_rows=len(evidence),evaluation_cases=counts,
                demo_cases=3,offline_tests_run=result.testsRun,offline_test_failures=len(result.failures),
                offline_test_errors=len(result.errors),data_integrity='passed',
                model_evaluation='NOT RUN: no model API invoked; natural-language cases are fixtures, not measured accuracy.',
                human_review=human_review_status(catalog['dataset_version']))
    output=ROOT/'data/validation'
    output.mkdir(parents=True,exist_ok=True)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (output/'offline_tests.txt').write_text(stream.getvalue())
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not result.wasSuccessful():raise SystemExit(1)

if __name__=='__main__':main()
