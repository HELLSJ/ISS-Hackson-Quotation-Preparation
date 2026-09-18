"""Small offline tools for the data package, callable by a future Agent backend.

Usage: python scripts/catalog_tools.py search_products '{"usb_c_video":true}'
No model calls, network, approvals, document export or quote persistence.
"""
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ToolError(ValueError):
    pass

def integer(value, name, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ToolError(f'{name} must be an integer between {minimum} and {maximum if maximum is not None else "unbounded"}')
    return value

class CatalogTools:
    def __init__(self, path=None):
        self.data = json.loads(Path(path or ROOT/'data/agent/catalog.json').read_text())
        self.products = {p['sku']:p for p in self.data['products']}
        self.rules = self.data['rules']

    def get_product(self, sku):
        if not isinstance(sku, str) or sku not in self.products:
            raise ToolError('UNKNOWN_SKU')
        return self.products[sku]

    def search_products(self, query=None, usb_c_video=None, min_pd_watts=None,
                        min_screen_inches=None, max_screen_inches=None, resolution=None,
                        min_refresh_hz=None, max_unit_price_cents=None):
        if query is not None and not isinstance(query,str):
            raise ToolError('query must be text')
        if usb_c_video is not None and type(usb_c_video) is not bool:
            raise ToolError('usb_c_video must be boolean')
        for k,v in [('min_pd_watts',min_pd_watts),('min_refresh_hz',min_refresh_hz),('max_unit_price_cents',max_unit_price_cents)]:
            if v is not None: integer(v,k)
        for k,v in [('min_screen_inches',min_screen_inches),('max_screen_inches',max_screen_inches)]:
            if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v <= 0):
                raise ToolError(k+' must be a positive finite number')
        if min_screen_inches is not None and max_screen_inches is not None and min_screen_inches > max_screen_inches:
            raise ToolError('Screen minimum exceeds maximum')
        if resolution is not None and not isinstance(resolution,str):
            raise ToolError('resolution must be text such as 2560x1440')
        terms = query.casefold().split() if query else []
        exact_skus = {p['sku'] for p in self.products.values() if query and query.casefold() in
                      [p['model'].casefold(),p['sku'].casefold(),*[a.casefold() for a in p['aliases']]]}
        results = []
        for p in self.products.values():
            if exact_skus and p['sku'] not in exact_skus: continue
            # query is a model/name keyword lookup, not a natural-language parser.
            text = ' '.join([p['name'],p['sku'],*p['aliases']]).casefold()
            exact = query and query.casefold() in [p['model'].casefold(),p['sku'].casefold()]
            if terms and not exact and not all(t in text for t in terms): continue
            if usb_c_video is not None and p['usb_c_video'] is not usb_c_video: continue
            if min_pd_watts is not None and (p['usb_c_pd_watts'] is None or p['usb_c_pd_watts']<min_pd_watts): continue
            if min_screen_inches is not None and (p['screen_inches'] is None or p['screen_inches']<min_screen_inches): continue
            if max_screen_inches is not None and (p['screen_inches'] is None or p['screen_inches']>max_screen_inches): continue
            if resolution is not None and p['resolution'] != resolution: continue
            if min_refresh_hz is not None and (p['max_refresh_hz'] is None or p['max_refresh_hz']<min_refresh_hz): continue
            price = p.get('price')
            if max_unit_price_cents is not None and (not price or price['unit_price_cents']>max_unit_price_cents): continue
            results.append(p)
        # Exact-model selection was applied before constraints; a conflict must
        # remain no-match rather than silently substituting a suffixed model.
        results.sort(key=lambda p:(p.get('price',{}).get('unit_price_cents',float('inf')),p['sku']))
        return {'dataset_version':self.data['dataset_version'],'count':len(results),'products':results}

    def calculate_quote(self, items, budget_cents=None):
        if not isinstance(items,list) or not items:
            raise ToolError('items must be a non-empty list')
        if budget_cents is not None: integer(budget_cents,'budget_cents')
        lines, seen = [], set()
        for item in items:
            if not isinstance(item,dict) or set(item)-{'sku','quantity','discount_bps'}:
                raise ToolError('Only sku, quantity and discount_bps are accepted; prices come from the catalogue')
            p = self.get_product(item.get('sku'))
            if p['sku'] in seen: raise ToolError('DUPLICATE_SKU: consolidate quantities into one line')
            seen.add(p['sku'])
            qty = integer(item.get('quantity'),'quantity',minimum=1)
            discount = integer(item.get('discount_bps',0),'discount_bps',maximum=self.rules['discount_limit_bps'])
            price = p.get('price')
            if not price or price.get('unit_price_cents') is None: raise ToolError('MISSING_PRICE')
            unit = integer(price['unit_price_cents'],'unit_price_cents')
            if price['currency'] != self.rules['currency']: raise ToolError('CURRENCY_MISMATCH')
            if price['price_version'] != self.rules['price_version']: raise ToolError('PRICE_VERSION_MISMATCH')
            gross = unit*qty
            deduction = (gross*discount+5000)//10000
            lines.append(dict(sku=p['sku'],model=p['model'],quantity=qty,unit_price_cents=unit,
                              discount_bps=discount,gross_cents=gross,discount_cents=deduction,
                              net_cents=gross-deduction,price_source_type='synthetic'))
        subtotal = sum(l['net_cents'] for l in lines)
        total = subtotal+self.rules['shipping_fee_cents']
        return dict(status='draft_requires_review',dataset_version=self.data['dataset_version'],
                    price_version=self.rules['price_version'],rule_version=self.rules['rule_version'],
                    currency=self.rules['currency'],items=lines,subtotal_cents=subtotal,
                    shipping_fee_cents=self.rules['shipping_fee_cents'],total_cents=total,
                    budget_cents=budget_cents,within_budget=None if budget_cents is None else total<=budget_cents,
                    over_budget_cents=None if budget_cents is None else max(0,total-budget_cents),
                    tax_mode=self.rules['tax_mode'],tax_note=self.rules['tax_note'],
                    stock_verified=False,delivery_verified=False)

    def dispatch(self, name, arguments):
        if name not in ('search_products','get_product','calculate_quote'):
            raise ToolError('UNKNOWN_TOOL')
        if not isinstance(arguments,dict): raise ToolError('Tool arguments must be an object')
        try:
            return getattr(self,name)(**arguments)
        except TypeError as exc:
            raise ToolError('INVALID_ARGUMENTS: '+str(exc)) from exc

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool',choices=['search_products','get_product','calculate_quote'])
    parser.add_argument('arguments',help='JSON object')
    args = parser.parse_args()
    try:
        result = CatalogTools().dispatch(args.tool,json.loads(args.arguments))
    except (ToolError,json.JSONDecodeError) as exc:
        print(json.dumps({'error':str(exc)}))
        raise SystemExit(2)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
