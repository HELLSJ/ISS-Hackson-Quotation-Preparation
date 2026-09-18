import json
import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from catalog_tools import CatalogTools,ToolError

class CatalogueTests(unittest.TestCase):
    def setUp(self): self.tools=CatalogTools()
    def test_usb_video_and_host_power(self):
        result=self.tools.search_products(usb_c_video=True,min_pd_watts=90)
        self.assertEqual({p['sku'] for p in result['products']},{'MON-007','MON-008','MON-009','MON-011'})
    def test_data_only_not_video(self):
        self.assertEqual(self.tools.search_products(query='U2724D',usb_c_video=True)['count'],0)
        self.assertEqual(self.tools.get_product('MON-010')['usb_c_downstream_charge_watts'],15)
    def test_no_4k_90w(self):
        self.assertEqual(self.tools.search_products(resolution='3840x2160',min_pd_watts=90)['count'],0)
    def test_exact_model(self):
        self.assertEqual([p['model'] for p in self.tools.search_products(query='P2425')['products']],['P2425'])
        self.assertEqual(self.tools.search_products(query='Dell U2724D',usb_c_video=True)['count'],0)
    def test_actual_diagonal(self):
        self.assertEqual(self.tools.search_products(query='P2425HE',min_screen_inches=24)['count'],0)
    def test_unknown_never_satisfies_filter(self):
        self.tools.products['MON-007']['usb_c_video']=None
        self.tools.products['MON-008']['usb_c_pd_watts']=None
        skus={p['sku'] for p in self.tools.search_products(usb_c_video=True,min_pd_watts=65)['products']}
        self.assertNotIn('MON-007',skus); self.assertNotIn('MON-008',skus)
    def test_budget(self):
        a=self.tools.calculate_quote([{'sku':'MON-007','quantity':8}],250000)
        b=self.tools.calculate_quote([{'sku':'MON-007','quantity':10}],250000)
        self.assertEqual(a['total_cents'],231200);self.assertTrue(a['within_budget'])
        self.assertEqual(b['over_budget_cents'],39000);self.assertFalse(b['within_budget'])
    def test_input_validation(self):
        for quantity in [None,0,-1,1.5,True,'2']:
            with self.subTest(quantity=quantity),self.assertRaises(ToolError):
                self.tools.calculate_quote([{'sku':'MON-001','quantity':quantity}])
        for bps in [-1,501,600,True,1.5]:
            with self.subTest(bps=bps),self.assertRaises(ToolError):
                self.tools.calculate_quote([{'sku':'MON-001','quantity':2,'discount_bps':bps}])
    def test_price_override_rejected(self):
        with self.assertRaises(ToolError):self.tools.calculate_quote([{'sku':'MON-001','quantity':1,'unit_price_cents':1}])
    def test_missing_price_rejected(self):
        self.tools.products['MON-001']['price']=None
        with self.assertRaises(ToolError):self.tools.calculate_quote([{'sku':'MON-001','quantity':1}])
    def test_duplicate_rejected(self):
        with self.assertRaises(ToolError):self.tools.calculate_quote([{'sku':'MON-001','quantity':1}]*2)
    def test_unsupported_arguments_rejected(self):
        with self.assertRaises(ToolError):self.tools.dispatch('search_products',{'stock':True})
        with self.assertRaises(ToolError):self.tools.dispatch('delete_all',{})
    def test_half_up_at_half_cent(self):
        self.tools.products['MON-001']['price']['unit_price_cents']=101
        self.assertEqual(self.tools.calculate_quote([{'sku':'MON-001','quantity':1,'discount_bps':500}])['total_cents'],96)
        self.tools.products['MON-001']['price']['unit_price_cents']=110
        self.assertEqual(self.tools.calculate_quote([{'sku':'MON-001','quantity':1,'discount_bps':500}])['total_cents'],104)
    def test_independent_expected_amounts(self):
        for line in (ROOT/'data/evaluation/expected_results.jsonl').read_text().splitlines():
            case=json.loads(line); e=case['expected']
            if 'items' not in e:continue
            with self.subTest(case=case['case_id']):
                independent=0
                for item in e['items']:
                    gross=Decimal(self.tools.products[item['sku']]['price']['unit_price_cents'])*item['quantity']
                    deduction=(gross*Decimal(item.get('discount_bps',0))/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
                    independent+=int(gross-deduction)
                self.assertEqual(independent,e['total_cents'])
                self.assertEqual(self.tools.calculate_quote(e['items'])['total_cents'],independent)

if __name__=='__main__':unittest.main()
