"""Find repeated visible password glyph pixels that text OCR can omit.

This deliberately narrow fallback needs both a recognized password label and a
run of small, filled, similarly shaped components. It never infers field bounds.
"""
import io
import re

import cv2
import numpy as np
from PIL import Image


def find_password_glyphs(png: bytes, regions: list[dict]) -> list[dict]:
    labels = [r for r in regions if re.fullmatch(r"(?:password|passcode)\s*[:：]?", r['text'].strip(), re.I)]
    if not labels:
        return []
    with Image.open(io.BytesIO(png)) as image:
        gray = np.asarray(image.convert('RGB'))
    gray = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    results, seen = [], set()
    for label in labels:
        lx, ly, lw, lh = (float(label[k]) for k in ('x','y','width','height'))
        x0, y0 = max(0,int(lx-8)), max(0,int(ly-4))
        x1 = min(width,int(lx+max(lw+320,400)))
        y1 = min(height,int(ly+lh+max(70,lh*3)))
        crop = gray[y0:y1,x0:x1]
        if crop.size == 0:
            continue
        # Fixed high contrast thresholds avoid turning gentle background gradients
        # into fabricated glyphs. Try both polarities for light and dark fields.
        for binary in [(crop < 110).astype('uint8'), (crop > 180).astype('uint8')]:
            count, components, stats, centers = cv2.connectedComponentsWithStats(binary,8)
            candidates=[]
            for index in range(1,count):
                x,y,w,h,area=map(int,stats[index])
                if not (2 <= w <= 14 and 2 <= h <= 14 and .65 <= w/h <= 1.55 and .25 <= area/(w*h) <= 1):
                    continue
                gx,gy=x+x0,y+y0
                right=gx >= lx+lw-2 and abs((gy+h/2)-(ly+lh/2)) <= max(10,lh*.6)
                # Allow later glyphs to extend to the right of the first one.
                below=gy >= ly+lh-2 and gx >= lx-8
                if not (below or right):
                    continue
                shape=(components[y:y+h,x:x+w]==index).astype('uint8')
                center=shape[max(0,h//2-1):min(h,h//2+1),max(0,w//2-1):min(w,w//2+1)]
                if center.mean() < .7:  # reject hollow letters and outlined dots
                    continue
                candidates.append((gx,gy,w,h,area,shape))
            candidates.sort(key=lambda c:c[0])
            for first in candidates:
                run=[first]; pitch=None
                for candidate in candidates:
                    previous=run[-1]
                    if candidate[0] <= previous[0]:
                        continue
                    dx=candidate[0]-previous[0]
                    if dx > first[2]*3+4:
                        break
                    if abs(candidate[1]-first[1])>1 or abs(candidate[2]-first[2])>1 or abs(candidate[3]-first[3])>1:
                        continue
                    if not (.7 <= candidate[4]/first[4] <= 1.3) or dx < first[2]+1:
                        continue
                    if pitch is not None and abs(dx-pitch)>1:
                        continue
                    normalized=cv2.resize(candidate[5],(first[2],first[3]),interpolation=cv2.INTER_NEAREST)
                    if np.mean(normalized == first[5]) < .8:
                        continue
                    run.append(candidate);pitch=dx if pitch is None else pitch
                if len(run)<3:
                    continue
                # A 1px dotted border has already failed minimum dimensions;
                # prevent long dotted rules and broad runs spanning the page.
                if len(run)>32 or run[-1][0]-run[0][0]>320:
                    continue
                # Dot accents in recognized prose (e.g. repeated i's) are not
                # missing password glyphs. Preserve OCR's own classification.
                prose = [r for r in regions if not re.fullmatch(
                    r"[•●·*▪\s]{3,}", r['text'])]
                if any(r['x'] <= c[0]+c[2]/2 < r['x']+r['width']
                       and r['y'] <= c[1]+c[3]/2 < r['y']+r['height']
                       for r in prose for c in run):
                    continue
                left=max(0,run[0][0]-3);top=max(0,min(c[1] for c in run)-3)
                right=min(width,max(c[0]+c[2] for c in run)+3)
                bottom=min(height,max(c[1]+c[3] for c in run)+3)
                key=(left,top,right,bottom)
                if any(left>=a and top>=b and right<=c and bottom<=d for a,b,c,d in seen):
                    continue
                seen.add(key)
                results.append(dict(text='•'*len(run),x=left,y=top,width=right-left,height=bottom-top,
                                    confidence=float(label.get('confidence',0.5)),source='pixel-password-glyphs'))
    return results
