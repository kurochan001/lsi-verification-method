"""Check saved pixels independently of HDL completion and emit actual PPM frames."""
import csv
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('video_compare_model',HERE/'model.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


def compare(directory,width,height,frames,seed,final_epoch,context):
    words=[int(line,16) for line in (directory/'blend.hex').read_text().splitlines()]
    total=width*height*frames
    if len(words)!=2*total:raise ValueError('reference packet count differs')
    counts={0:0,1:0};errored={0:False,1:False};images={};black_pixels=0
    with (directory/'pixels.csv').open() as stream:
        reader=csv.DictReader(stream)
        if reader.fieldnames!=['epoch','frame','x','y','rgb','error']:raise ValueError('pixel CSV columns differ')
        for row in reader:
            epoch,frame,x,y,error=(int(row[k]) for k in ('epoch','frame','x','y','error'))
            actual=int(row['rgb'],16)
            if epoch not in counts or epoch>final_epoch or error not in (0,1) or not 0<=actual<=0xffffff or not 0<=x<width or not 0<=y<height:
                raise ValueError('invalid output pixel fields: '+str(row))
            index=frame*width*height+y*width+x
            if index!=counts[epoch]:raise ValueError(f'{context} epoch={epoch} frame={frame} x={x} y={y} missing/duplicate/out-of-order pixel')
            counts[epoch]+=1
            if errored[epoch] and not error:raise ValueError('video error cleared without reset')
            errored[epoch] |= bool(error)
            expected=0 if error else words[epoch*total+index]&0xffffff if index<total else None
            if actual!=expected:
                raise ValueError(f'{context} epoch={epoch} frame={frame} x={x} y={y} expected={expected!r} actual=0x{actual:06x}')
            if error:black_pixels+=1
            images.setdefault((epoch,frame),[]).append(tuple((actual>>s)&255 for s in (16,8,0)))
    if counts[final_epoch]!=total or errored[final_epoch]:
        raise ValueError(f'{context} final generation incomplete or erroneous: {counts}, {errored}')
    for (epoch,frame),pixels in images.items():
        if len(pixels)==width*height:M.write_ppm(directory/f'actual-e{epoch}-f{frame}.ppm',width,height,pixels)
    return dict(pixels=counts,black_error_pixels=black_pixels,complete_images=sum(len(v)==width*height for v in images.values()),mismatches=0)
