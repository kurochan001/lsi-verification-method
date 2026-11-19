"""Independent frame images and checks of every fixed-timing display cycle."""
import csv
from pathlib import Path
import random


def image(width,height,frame,seed):
    rng=random.Random(seed*257+frame)
    return [((frame*37+x*19+rng.randrange(16))%256,
             (frame*13+y*43+rng.randrange(16))%256,
             (frame*71+x*7+y*11)%256) for y in range(height) for x in range(width)]


def ppm(path,width,height,pixels):
    Path(path).write_bytes(f'P6\n{width} {height}\n255\n'.encode()+bytes(v for pixel in pixels for v in pixel))


def vectors(width,height,seed):
    rows=[]
    for frame in range(65,69):
        for index,(r,g,b) in enumerate(image(width,height,frame,seed)):
            rows.append([r<<16|g<<8|b,int(index==0),int(index%width==width-1),frame])
    return rows


def compare(case,directory):
    p=case['parameters'];w,h=p['WIDTH'],p['HEIGHT'];ht,vt=w+4,h+3
    expected={f:image(w,h,f,case['seed']) for f in range(65,69)}
    for frame,pixels in expected.items():ppm(directory/f'expected-{frame}.ppm',w,h,pixels)
    accepted=list(csv.DictReader((directory/'trace.csv.accepted').read_text().splitlines()))
    wanted=vectors(w,h,case['seed'])
    final=[r for r in accepted if int(r['generation'])==1]
    if len(final)!=len(wanted):raise ValueError('accepted input completion count differs')
    for index,(actual,reference) in enumerate(zip(final,wanted)):
        if [int(actual['rgb'],16),int(actual['sof']),int(actual['eol']),int(actual['frame'])]!=reference:
            raise ValueError(f'input acceptance differs at {index}')
    rows=list(csv.DictReader((directory/'trace.csv').read_text().splitlines()))
    if len(rows)!=case['checks']:raise ValueError('display log is truncated')
    last_frame=64;current=None;pixels=[];repeats=0;completed=set()
    def failure(message,index,frame,x,y,exp,got):
        return dict(success=False,message=f"seed={case['seed']} cycle={index} frame={frame} x={x} y={y} expected={exp} actual={got} clocks={p['WR_PERIOD']}/{p['PIX_PERIOD']} size={w}x{h}: {message}")
    for index,row in enumerate(rows):
        y,x=divmod(index%(ht*vt),ht)
        active=x<w and y<h
        exp_signals=(int(active),int(not(w+2<=x<w+3)),int(not(h+1<=y<h+2)))
        try:
            signals=tuple(int(row[k]) for k in ('de','hsync','vsync'))
            frame=int(row['frame']);valid=int(row['valid']);packed=int(row['rgb'],16)
        except ValueError:return failure('X/Z in output',index,-1,x,y,'known',row)
        got=(packed>>16,(packed>>8)&255,packed&255)
        if int(row['cycle'])!=index or signals!=exp_signals:
            return failure('display timing differs',index,frame,x,y,exp_signals,signals)
        if x==0 and y==0:
            if valid:
                if frame not in (last_frame,last_frame+1) or frame not in expected:
                    return failure('frame was lost, reordered or from an old generation',index,frame,x,y,last_frame+1,frame)
                repeats+=int(frame==last_frame);last_frame=frame;current=frame;pixels=[]
            else:
                if last_frame!=64:return failure('display became invalid after startup',index,frame,x,y,1,0)
                current=None
        if active:
            if bool(valid)!=(current is not None) or (valid and frame!=current):
                return failure('frame switched away from the frame boundary',index,frame,x,y,current,frame)
            exp=expected[current][y*w+x] if valid else (0,0,0)
            if got!=exp:return failure('pixel differs',index,frame,x,y,exp,got)
            if valid:
                pixels.append(got)
                if x==w-1 and y==h-1:
                    ppm(directory/f'actual-{frame}.ppm',w,h,pixels);completed.add(frame)
        elif valid or packed!=0:
            return failure('blanking is not black or consumed a pixel',index,frame,x,y,(0,0,0),got)
    if completed!=set(expected) or not repeats:
        return dict(success=False,message=f"seed={case['seed']} cycle={len(rows)} frame={last_frame} x=0 y=0 clocks={p['WR_PERIOD']}/{p['PIX_PERIOD']} size={w}x{h} expected_frames={sorted(expected)} completed_frames={sorted(completed)} repeated={repeats}")
    return dict(success=True,message=f'{len(rows)} timing cycles and all pixels matched',frames=sorted(completed),repeated_frames=repeats)
