"""Independent integer image oracle; no RTL, pointer, or streaming implementation."""
import random
from pathlib import Path

KEY=(81,144,90)


def csc(y,cb,cr):
    if any(type(v) is not int or not 0<=v<=255 for v in (y,cb,cr)):
        raise ValueError('YCbCr components must be eight-bit integers')
    c,d,e=y-16,cb-128,cr-128
    values=(298*c+409*e,298*c-100*d-208*e,298*c+516*d)
    return tuple(max(0,min(255,(v+128)//256)) for v in values)


def blend(foreground,background,alpha):
    if len(foreground)!=3 or len(background)!=3 or any(type(v) is not int or not 0<=v<=255 for v in (*foreground,*background,alpha)):
        raise ValueError('RGB and alpha must be eight-bit integers')
    return tuple((alpha*f+(255-alpha)*b+127)//255 for f,b in zip(foreground,background))


def pack(components,alpha,background,sof,eol):
    value=(int(sof)<<1)|int(eol)
    for v in (*components,alpha,*background):
        if not 0<=v<=255:raise ValueError('component outside eight-bit range')
        value=(value<<8)|v
    return value


def transform(packet):
    components=tuple((packet>>shift)&255 for shift in (48,40,32))
    alpha=(packet>>24)&255
    background=tuple((packet>>shift)&255 for shift in (16,8,0))
    sof,eol=(packet>>57)&1,(packet>>56)&1
    keyed_alpha=0 if components==KEY else alpha
    foreground=csc(*components)
    rgb=blend(foreground,background,keyed_alpha)
    keyed=pack(components,keyed_alpha,background,sof,eol)
    converted=pack(foreground,keyed_alpha,background,sof,eol)
    output=(sof<<25)|(eol<<24)|(rgb[0]<<16)|(rgb[1]<<8)|rgb[2]
    return keyed,converted,output


def image_packets(width,height,frames,seed,epoch=0):
    rng=random.Random((seed<<8)+epoch)
    colors=[KEY,(KEY[0]+1,KEY[1],KEY[2]),(16,128,128),(235,128,128),
            (81,90,240),(145,54,34),(41,240,110),(0,0,0),(255,255,255)]
    result=[]
    for frame in range(frames):
        for y in range(height):
            for x in range(width):
                i=y*width+x
                ycc=colors[(i+frame+epoch*3)%len(colors)] if i%4 else tuple(rng.randrange(256) for _ in range(3))
                # Include exact transparent keys at SOF and at EOL without deleting them.
                if i==0 or x==width-1:ycc=KEY
                alpha=(0,1,127,128,254,255)[(i+frame+epoch)%6]
                bg=((x*11+frame*31+epoch*73)%256,(y*17+epoch*47)%256,(x+y+frame*67+epoch*109)%256)
                result.append(pack(ycc,alpha,bg,i==0,x==width-1))
    return result


def write_hex(path,values):
    Path(path).write_text(''.join(f'{v:x}\n' for v in values))


def write_ppm(path,width,height,rgb):
    if len(rgb)!=width*height:raise ValueError('PPM needs a complete frame')
    payload=bytes(component for pixel in rgb for component in pixel)
    Path(path).write_bytes(f'P6\n{width} {height}\n255\n'.encode()+payload)


def prepare(directory,width,height,frames,seed):
    raw=[]
    for epoch in (0,1):raw.extend(image_packets(width,height,frames,seed,epoch))
    stages=list(zip(*(transform(p) for p in raw)))
    write_hex(directory/'input.hex',raw)
    for name,words in zip(('key','csc','blend'),stages):write_hex(directory/(name+'.hex'),words)
    for epoch in (0,1):
        for frame in range(frames):
            start=(epoch*frames+frame)*width*height
            pixels=[tuple((v>>shift)&255 for shift in (16,8,0)) for v in stages[2][start:start+width*height]]
            write_ppm(directory/f'expected-e{epoch}-f{frame}.ppm',width,height,pixels)
    return raw,stages


def arithmetic_vectors(seed=17):
    rng=random.Random(seed);rows=[]
    colors=[KEY,(KEY[0]+1,KEY[1],KEY[2]),(KEY[0],KEY[1]+1,KEY[2]),
            (KEY[0],KEY[1],KEY[2]+1),(16,128,128),(235,128,128),
            (81,90,240),(145,54,34),(41,240,110)]
    colors += [(y,cb,cr) for y in (0,15,16,17,128,234,235,255) for cb in (0,127,128,129,255) for cr in (0,127,128,129,255)]
    colors += [tuple(rng.randrange(256) for _ in range(3)) for _ in range(128)]
    for i,color in enumerate(colors):
        alpha=(0,1,127,128,254,255)[i%6];bg=(13,77,241)
        packet=pack(color,alpha,bg,i%3==0,i%5==0)
        keyed,converted,_=transform(packet)
        rows.extend(((0,packet,keyed),(1,packet,pack(csc(*color),alpha,bg,i%3==0,i%5==0))))
    for alpha in (0,1,127,128,254,255):
        for fg in ((0,0,0),(255,255,255),(1,127,254),(240,33,128)):
            for bg in ((255,0,17),(0,255,250),(13,77,241)):
                packet=pack(fg,alpha,bg,True,False);rgb=blend(fg,bg,alpha)
                rows.append((2,packet,(1<<25)|(rgb[0]<<16)|(rgb[1]<<8)|rgb[2]))
    return rows
