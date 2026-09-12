from __future__ import annotations
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/naver-smarteditor-drafter/scripts'))
from asset_integrity import inspect_asset,verify_asset
from post_contract import BuildError

class AssetIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()
    def asset(self,name='image.png'):
        p=self.root/name;Image.new('RGB',(8,6),'white').save(p);return p
    def test_png_and_jpeg_decode(self):
        for name in ['image.png','image.jpg','image.jpeg']:
            p=self.asset(name);info=inspect_asset(p,self.root)
            self.assertEqual((info['width'],info['height']),(8,6));self.assertEqual(verify_asset(info,self.root),info)
    def test_corruption_and_extension(self):
        p=self.asset();data=p.read_bytes();p.write_bytes(data[:20])
        with self.assertRaises(BuildError):inspect_asset(p,self.root)
        mismatch=self.root/'bad.jpg';mismatch.write_bytes(data)
        with self.assertRaisesRegex(BuildError,'mismatch'):inspect_asset(mismatch,self.root)
    def test_asset_change_and_symlink_escape(self):
        p=self.asset();record=inspect_asset(p,self.root);Image.new('RGB',(8,6),'black').save(p)
        with self.assertRaises(BuildError) as ctx:verify_asset(record,self.root)
        self.assertEqual(ctx.exception.code,'ASSET_CHANGED')
        with tempfile.TemporaryDirectory() as outside:
            remote=Path(outside)/'other.png';remote.write_bytes(p.read_bytes());link=self.root/'link.png';link.symlink_to(remote)
            with self.assertRaises(BuildError):inspect_asset(link,self.root)
    def test_pixel_and_byte_safety_limits(self):
        p=self.asset()
        with patch('asset_integrity.MAX_PIXELS',10),self.assertRaises(BuildError):inspect_asset(p,self.root)
        with patch('asset_integrity.MAX_FILE_BYTES',10),self.assertRaises(BuildError):inspect_asset(p,self.root)
    def test_missing_dependency_fails_closed(self):
        p=self.asset()
        with patch.dict(sys.modules,{'PIL':None}),self.assertRaises(BuildError) as ctx:inspect_asset(p,self.root)
        self.assertEqual(ctx.exception.code,'DEPENDENCY_MISSING')

if __name__=='__main__':unittest.main()
