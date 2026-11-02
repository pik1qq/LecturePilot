"""Create crisp, multi-resolution vector-inspired light/dark application marks."""
from pathlib import Path
from PIL import Image,ImageDraw
BASE=Path(__file__).resolve().parent
# A single page/route mark: simple enough to remain legible on a 16px taskbar.
VARIANTS={'':('#294F47','#FFFFFF','#A8D2C0'),'-dark':('#4A4D4B','#FAFAF8','#C8CECA')}

def render(background,foreground,accent,size=512):
    # Hint the small frames to the pixel grid. Fine text-like details in a
    # downsampled 512px picture otherwise turn into blurry grey pixels.
    if size <= 48:
        im=Image.new('RGBA',(size,size),(0,0,0,0));d=ImageDraw.Draw(im)
        k=lambda v:round(v*size/32)
        d.rounded_rectangle((k(1),k(1),k(31)-1,k(31)-1),radius=max(2,k(7)),fill=background)
        d.rounded_rectangle((k(6),k(5),k(22),k(27)),radius=max(1,k(2)),fill=foreground)
        stroke=max(1,round(size/32))
        for y,end in [(10,19),(14,18),(18,15)]:
            d.rectangle((k(9),k(y),k(end),k(y)+stroke-1),fill=background)
        d.ellipse((k(19),k(18),k(29),k(28)),fill=background)
        d.ellipse((k(20),k(19),k(28),k(27)),fill=accent)
        d.polygon([(k(23),k(21)),(k(23),k(25)),(k(26),k(23))],fill=background)
        return im
    factor=4; im=Image.new('RGBA',(256*factor,256*factor),(0,0,0,0)); d=ImageDraw.Draw(im)
    def box(coords):return tuple(int(x*factor) for x in coords)
    d.rounded_rectangle(box((10,10,246,246)),radius=52*factor,fill=background)
    # Broad page silhouette; three robust lines retain their shape at taskbar size.
    d.rounded_rectangle(box((55,52,171,204)),radius=13*factor,fill=foreground)
    for y,width in [(79,75),(104,64),(129,49)]:
        d.rounded_rectangle(box((74,y,74+width,y+14)),radius=5*factor,fill=background)
    # Distinct forward arrow represents the pilot, not a tiny detailed logo.
    d.ellipse(box((140,134,214,208)),fill=background)
    d.ellipse(box((148,142,206,200)),fill=accent)
    d.polygon([(170*factor,155*factor),(170*factor,188*factor),(192*factor,171*factor)],fill=background)
    return im.resize((size,size),Image.Resampling.LANCZOS)

def svg(background,foreground,accent):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect x="10" y="10" width="236" height="236" rx="52" fill="{background}"/><rect x="55" y="52" width="116" height="152" rx="13" fill="{foreground}"/><path d="M78 84h67M78 109h56M78 134h41" fill="none" stroke="{background}" stroke-width="14" stroke-linecap="round"/><circle cx="177" cy="171" r="37" fill="{background}"/><circle cx="177" cy="171" r="29" fill="{accent}"/><path d="M170 155v33l22-17z" fill="{background}"/></svg>'''
for suffix,(bg,fg,accent) in VARIANTS.items():
    im=render(bg,fg,accent)
    im.save(BASE/('app-icon'+suffix+'.png'))
    sizes=[16,20,24,30,32,36,40,48,60,64,72,96,128,256]
    frames=[render(bg,fg,accent,size) for size in sizes]
    im.save(BASE/('app-icon'+suffix+'.ico'),format='ICO',sizes=[(n,n) for n in sizes],append_images=frames)
    (BASE/('app-icon'+suffix+'.svg')).write_text(svg(bg,fg,accent),encoding='utf-8')
print('Generated light/dark SVG, PNG and multi-resolution Windows ICO icons.')
