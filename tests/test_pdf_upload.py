"""PDF 转图后的接收边界：引用、重复页、重试、旧草稿升级；无需 PDF/Pillow 依赖。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_core
from clms import drafts, ledger, source_export

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


class PdfUploadTests(test_core.ServerFlowTests):
    test_full_flow = None

    def test_pages_share_image_but_keep_identity_and_retry_is_idempotent(self):
        before = ledger.verify_ledger(self.vault)
        code, saved = self.call('/api/image', {'name': 'page.jpg', 'data': PNG})
        self.assertEqual(code, 200, saved)
        token = 'a' * 32
        images = [{'image': saved['image'], 'source': {'name': '试卷.pdf', 'page': n, 'import_id': token}}
                  for n in (1, 2, 3)]
        payload = {'images': images, 'upload_id': token}
        code, result = self.call('/api/drafts', payload)
        self.assertEqual(code, 200, result)
        draft = result['drafts'][0]
        self.assertEqual(len(draft['pages']), 3)
        self.assertEqual(len(set(draft['images'])), 1)
        self.assertEqual(len({p['id'] for p in draft['pages']}), 3)
        _, again = self.call('/api/drafts', payload)
        self.assertEqual(again['drafts'][0]['id'], draft['id'])
        pages = list(reversed(draft['pages']))
        pages[0].update(rotate=90, note='答案页')
        code, result = self.call('/api/draft/pages', {'id': draft['id'], 'pages': pages})
        self.assertEqual(code, 200, result)
        self.assertEqual(result['pages'][0]['source']['page'], 3)
        self.assertEqual(result['pages'][0]['note'], '答案页')
        _, result = self.call('/api/draft/pages', {'id': draft['id'], 'add': images})
        self.assertEqual(len(result['pages']), 3)
        images[0]['source']['import_id'] = 'b' * 32
        _, result = self.call('/api/draft/pages', {'id': draft['id'], 'add': images[:1]})
        self.assertEqual(len(result['pages']), 4)
        self.assertEqual(ledger.verify_ledger(self.vault), before)

    def test_invalid_reference_or_source_does_not_append_pages(self):
        code, result = self.call('/api/drafts', {'images': [{'data': PNG}]})
        self.assertEqual(code, 200)
        draft = result['drafts'][0]
        for image in ({'image': '../ledger.db'}, {'image': '0' * 24 + '.png'},
                      {'image': draft['images'][0], 'source': {'page': 1, 'import_id': 'bad'}},
                      {'image': draft['images'][0], 'source': 'invalid'}):
            code, _ = self.call('/api/draft/pages', {'id': draft['id'], 'add': [image]})
            self.assertEqual(code, 400)
        self.assertEqual(drafts.load(self.vault, draft['id'])['pages'], draft['pages'])


class PdfCompatibilityTests(test_core.TempVault):
    def test_legacy_page_identity_survives_reorder(self):
        image = drafts.receive_image(self.vault, {'data': PNG})
        draft = drafts.create(self.vault, [image])
        draft['pages'][0].pop('id')
        drafts.save(self.vault, draft)
        first = drafts.load(self.vault, draft['id'])
        second = drafts.load(self.vault, draft['id'])
        self.assertEqual(first['pages'], second['pages'])
        first['pages'][0]['rotate'] = 90
        updated = drafts.update_pages(self.vault, draft['id'], first['pages'])
        self.assertEqual(updated['pages'][0]['id'], first['pages'][0]['id'])

    def test_export_keeps_pdf_runtime_resources_and_licenses(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        files, _ = source_export.source_files(root)
        for path in ('build/pdf.min.mjs', 'build/pdf.worker.min.mjs', 'LICENSE',
                     'cmaps/UniGB-UCS2-H.bcmap', 'standard_fonts/FoxitSerif.pfb', 'wasm/openjpeg.wasm'):
            self.assertIn('assets/vendor/pdfjs/' + path, files)


if __name__ == '__main__':
    unittest.main()
