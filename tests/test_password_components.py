import io
import unittest
from PIL import Image, ImageDraw, ImageFont
from plva.detection.password_glyphs import find_password_glyphs


class PasswordComponentTests(unittest.TestCase):
    def test_negatives_and_recognized_prose(self):
        label=dict(text='Password',x=25,y=20,width=100,height=25)
        for case in ('border','outline','caret','no_label','prose'):
            with self.subTest(case=case):
                image=Image.new('RGB',(600,200),'white');draw=ImageDraw.Draw(image)
                rows=[label]
                if case=='border':
                    for x in range(30,130,4):draw.point((x,75),fill='black')
                elif case=='outline':
                    draw.rectangle((30,65,250,95),outline='black')
                elif case=='caret':
                    draw.rectangle((30,65,31,90),fill='black')
                elif case=='no_label':
                    rows=[]
                    for x in range(30,90,5):draw.ellipse((x,75,x+3,78),fill='black')
                else:
                    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
                    draw.text((30,70),'iiiiiii',font=font,fill='black')
                    box=draw.textbbox((30,70),'iiiiiii',font=font)
                    rows.append(dict(text='iiiiiii',x=box[0]-2,y=box[1]-2,
                                     width=box[2]-box[0]+4,height=box[3]-box[1]+4))
                output=io.BytesIO();image.save(output,'PNG')
                self.assertEqual(find_password_glyphs(output.getvalue(),rows),[])
