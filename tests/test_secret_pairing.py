import io
import os
import unittest

from PIL import Image, ImageDraw, ImageFont
from plva.detection import ScreenshotDetector
from plva.detection.classify import classify_regions
from plva.privacy import PrivacySession, PrivacyError


def row(text, x=10, y=10, width=150):
    return dict(text=text, x=x, y=y, width=width, height=20, confidence=.99)


class SecretPairingTests(unittest.TestCase):
    def test_recovery_link_does_not_beat_bullets(self):
        findings = classify_regions([row('Password', width=85), row('Forgot password?',140), row('********', y=42)])
        self.assertEqual([(f['value'],f['x'],f['y']) for f in findings], [('********',10,42)])

    def test_helper_only_and_heading_do_not_become_secrets(self):
        self.assertEqual(classify_regions([row('Password',width=85), row('Use at least 8 characters',y=46)]), [])
        self.assertEqual(classify_regions([row('Password requirements')]), [])

    def test_side_and_below_values_remain_supported(self):
        for value in ['********', '••••••', 'arbitrary private passphrase']:
            for x,y in [(140,10),(10,42)]:
                findings=classify_regions([row('Password',width=85),row(value,x,y)])
                self.assertEqual(findings[0]['value'],value)

    def test_explicit_helper_shaped_secret_is_preserved_and_blocked(self):
        class OCR:
            text='Password: Forgot password?'
            def recognize(self,png):return [row(self.text)]
        ocr=OCR(); detector=ScreenshotDetector(ocr=ocr)
        first=detector.detect(b'fixture')
        self.assertEqual(first[0]['value'],'Forgot password?')
        ocr.text='Forgot password?'
        self.assertEqual(detector.detect(b'fixture')[0]['kind'],'SECRET')
        output=io.BytesIO();Image.new('RGB',(300,100),'white').save(output,'PNG')
        privacy=PrivacySession();privacy.protect(output.getvalue(),first)
        with self.assertRaises(PrivacyError):privacy.resolve('[SECRET_1]')

    def test_stale_helper_memory_ignored_but_legitimate_memory_preserved(self):
        known=[dict(kind='SECRET',value='Forgot password?'),dict(kind='SECRET',value='arbitrary private passphrase')]
        self.assertEqual(classify_regions([row('Forgot password?')],known),[])
        self.assertEqual(classify_regions([row('arbitrary private passphrase')],known)[0]['kind'],'SECRET')

    @unittest.skipUnless(os.environ.get('PLVA_TEST_OCR')=='1','explicit CPU OCR opt-in')
    def test_actual_ocr_secret_glyph_pixels_and_recovery_link(self):
        image=Image.new('RGB',(700,240),'white'); draw=ImageDraw.Draw(image)
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
        draw.text((30,25),'Password',font=font,fill='black')
        draw.text((260,25),'Forgot password?',font=font,fill='black')
        draw.text((30,85),'************',font=font,fill='black')
        box=draw.textbbox((30,85),'************',font=font)
        output=io.BytesIO();image.save(output,'PNG')
        findings=ScreenshotDetector().detect(output.getvalue())
        self.assertFalse(any(f['value']=='Forgot password?' for f in findings))
        protected=PrivacySession().protect(output.getvalue(),findings)
        safe=Image.open(io.BytesIO(protected['png'])).convert('RGB')
        coverage=Image.new('1',image.size);painter=ImageDraw.Draw(coverage)
        for m in protected['masks']:
            if m['kind']=='SECRET':painter.rectangle((m['x'],m['y'],m['x']+m['width']-1,m['y']+m['height']-1),fill=1)
        count=0
        for y in range(box[1],box[3]):
            for x in range(box[0],box[2]):
                if image.getpixel((x,y))!=(255,255,255):
                    count+=1
                    self.assertTrue(coverage.getpixel((x,y)))
                    self.assertNotEqual(image.getpixel((x,y)),safe.getpixel((x,y)))
        self.assertGreater(count,100)
