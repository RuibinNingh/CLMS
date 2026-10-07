"""Original-byte boundary: version ownership, symlinks, mutations, format and size."""
import base64
import io
import os
import unittest
from unittest.mock import patch

from test_core import TempVault
from clms import essays
from clms.mcp.images import read_essay_image


class MCPImageTests(TempVault):
    def setUp(self):
        super().setUp()
        # A complete minimal PNG; no Pillow needed for fixture creation.
        self.data = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/0CgAAAAASUVORK5CYII=')
        prompt = essays.create_prompt(self.vault, '题目', '请写完整作文。')
        self.attempt = essays.create_attempt(self.vault, prompt['id'])
        self.version = essays.create_version(self.vault, self.attempt['id'], [{'data': base64.b64encode(self.data).decode()}])
        self.path = essays.version_image_path(self.vault, self.version['id'], self.version['images'][0])

    def test_native_image_returns_original_bytes(self):
        value = read_essay_image(self.vault, self.version['id'])
        self.assertEqual(base64.b64decode(value['data']), self.data)
        self.assertEqual(value['mime_type'], 'image/png')

    def test_file_symlink_and_arbitrary_index_are_rejected(self):
        outside = os.path.join(self.vault, 'private.txt')
        with open(outside, 'wb') as stream:
            stream.write(self.data)
        os.unlink(self.path); os.symlink(outside, self.path)
        with self.assertRaises(ValueError):
            read_essay_image(self.vault, self.version['id'])
        for index in (-1, 1, True, '0'):
            with self.subTest(index=index), self.assertRaises(ValueError):
                read_essay_image(self.vault, self.version['id'], index)

    def test_directory_symlink_is_rejected(self):
        folder = os.path.dirname(self.path)
        replacement = folder + '-original'
        os.rename(folder, replacement); os.symlink(replacement, folder)
        with self.assertRaises(ValueError):
            read_essay_image(self.vault, self.version['id'])

    def test_swapped_or_oversize_image_is_rejected(self):
        with open(self.path, 'ab') as stream:
            stream.write(b'replaced')
        with self.assertRaises(ValueError):
            read_essay_image(self.vault, self.version['id'])
        with patch('clms.mcp.images.MAX_IMAGE_BYTES', 8):
            with self.assertRaises(ValueError):
                read_essay_image(self.vault, self.version['id'])


if __name__ == '__main__':
    unittest.main()
