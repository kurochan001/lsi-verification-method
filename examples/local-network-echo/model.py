"""Byte-oriented packet oracle using struct, one's-complement sums and zlib CRC-32.

It does not reproduce the RTL queue, streaming indices, or CRC shift register.
The byte interface includes DA through FCS, without preamble/SFD/IFG.
"""
import random
import struct
import zlib

LOCAL_MAC=bytes.fromhex('020000000001')
LOCAL_IP=bytes((192,0,2,1))
PEER_MAC=bytes.fromhex('020000000002')
PEER_IP=bytes((192,0,2,2))
PORT=1234
DROP={1:'crc',2:'length',3:'link',4:'filter',5:'format',6:'ip-checksum',7:'udp-checksum',8:'unsupported'}


def checksum(data):
    data=bytes(data)
    if len(data)%2:data+=b'\0'
    value=sum(struct.unpack('!'+str(len(data)//2)+'H',data)) if data else 0
    while value>>16:value=(value&0xffff)+(value>>16)
    return (~value)&0xffff


def with_fcs(body):
    body=bytes(body)
    return body+struct.pack('<I',zlib.crc32(body)&0xffffffff)


def arp(peer_mac=PEER_MAC,peer_ip=PEER_IP,target_ip=LOCAL_IP):
    body=b'\xff'*6+peer_mac+b'\x08\x06'+struct.pack('!HHBBH',1,0x0800,6,4,1)+peer_mac+peer_ip+b'\0'*6+target_ip
    return with_fcs(body.ljust(60,b'\0'))


def udp(payload=b'abc',peer_mac=PEER_MAC,peer_ip=PEER_IP,source_port=2468,destination_port=PORT,
        destination_ip=LOCAL_IP,zero_checksum=False,identification=0x1234):
    payload=bytes(payload);length=8+len(payload)
    header=struct.pack('!HHHH',source_port,destination_port,length,0)
    pseudo=peer_ip+destination_ip+struct.pack('!BBH',0,17,length)
    value=0 if zero_checksum else checksum(pseudo+header+payload) or 0xffff
    segment=header[:6]+struct.pack('!H',value)+payload
    ip=struct.pack('!BBHHHBBH4s4s',0x45,0,20+length,identification,0x4000,64,17,0,peer_ip,destination_ip)
    ip=ip[:10]+struct.pack('!H',checksum(ip))+ip[12:]
    return with_fcs((LOCAL_MAC+peer_mac+b'\x08\x00'+ip+segment).ljust(60,b'\0'))


def decode(frame,max_frame=128,link_error=False):
    """Return (canonical reply or None, rejection reason, ARP=1/UDP=2)."""
    frame=bytes(frame)
    if link_error:return None,3,0
    if not 64<=len(frame)<=max_frame:return None,2,0
    body=frame[:-4]
    if struct.pack('<I',zlib.crc32(body)&0xffffffff)!=frame[-4:]:return None,1,0
    destination,source,typ=body[:6],body[6:12],body[12:14]
    if destination!=LOCAL_MAC and not (typ==b'\x08\x06' and destination==b'\xff'*6):return None,4,0
    if typ==b'\x08\x06':
        if body[14:22]!=struct.pack('!HHBBH',1,0x0800,6,4,1):return None,8,0
        if body[22:28]!=source:return None,5,0
        if body[38:42]!=LOCAL_IP:return None,4,0
        reply=source+LOCAL_MAC+typ+struct.pack('!HHBBH',1,0x0800,6,4,2)+LOCAL_MAC+LOCAL_IP+body[22:32]
        return with_fcs(reply.ljust(60,b'\0')),0,1
    if typ!=b'\x08\x00':return None,8,0
    first,tos,total,ident,fragment,ttl,proto,ipcheck,sip,dip=struct.unpack('!BBHHHBBH4s4s',body[14:34])
    if first!=0x45 or fragment&0xbfff or proto!=17:return None,8,0
    sport,dport,length,udpcheck=struct.unpack('!HHHH',body[34:42])
    if total<28 or total+14>len(body) or length<8 or length!=total-20 or ttl==0:return None,5,0
    if checksum(body[14:34])!=0:return None,6,0
    if dip!=LOCAL_IP or dport!=PORT:return None,4,0
    pseudo=sip+dip+struct.pack('!BBH',0,17,length)
    if udpcheck and checksum(pseudo+body[34:34+length])!=0:return None,7,0
    payload=body[42:34+length]
    segment=struct.pack('!HHHH',dport,sport,length,0)+payload
    pseudo=LOCAL_IP+sip+struct.pack('!BBH',0,17,length)
    segment=segment[:6]+struct.pack('!H',checksum(pseudo+segment) or 0xffff)+payload
    ip=struct.pack('!BBHHHBBH4s4s',0x45,0,total,ident,fragment,64,17,0,LOCAL_IP,sip)
    ip=ip[:10]+struct.pack('!H',checksum(ip))+ip[12:]
    return with_fcs((source+LOCAL_MAC+typ+ip+segment).ljust(60,b'\0')),0,2


def edit(frame,changes,fix_ip=False):
    body=bytearray(frame[:-4])
    for index,value in changes.items():body[index]=value
    if fix_ip:
        body[24:26]=b'\0\0';body[24:26]=struct.pack('!H',checksum(body[14:34]))
    return with_fcs(body)


def zero_result_packet():
    base=udp(b'\0\0');body=base[:-4]
    pseudo=body[26:34]+struct.pack('!BBH',0,17,10)
    value=checksum(pseudo+body[34:40]+b'\0\0'+b'\0\0')
    return udp(struct.pack('!H',value))


def invalid_frames(max_frame):
    good=udp(b'odd');bad=bytearray(good);bad[-1]^=1;unsummed=udp(b'odd',zero_checksum=True);request=arp()
    return [dict(data=bytes(bad),reason=1),dict(data=with_fcs(b'\0'*10),reason=2),
            dict(data=good,link_error=True,reason=3),dict(data=edit(good,{0:0x04}),reason=4),
            dict(data=edit(good,{38:0,39:7}),reason=5),dict(data=edit(good,{24:good[24]^1}),reason=6),
            dict(data=edit(good,{40:good[40]^1}),reason=7),dict(data=edit(good,{14:0x46},True),reason=8),
            dict(data=edit(good,{20:0x20},True),reason=8),dict(data=edit(good,{22:0},True),reason=5),
            dict(data=udp(b'port',destination_port=PORT+1),reason=4),
            dict(data=arp(target_ip=bytes((192,0,2,9))),reason=4),
            dict(data=with_fcs(bytes(max_frame)),reason=2),
            # Each frame below passes every other check, so only the named term can reject it.
            dict(data=good,link_error=True,link_at=0,reason=3),dict(data=good,link_error=True,link_at=-1,reason=3),
            dict(data=udp(b'addr',destination_ip=bytes((192,0,2,9))),reason=4),
            dict(data=edit(good,{i:255 for i in range(6)}),reason=4),
            dict(data=edit(good,{12:0x86,13:0xdd}),reason=8),dict(data=edit(good,{23:6},True),reason=8),
            dict(data=edit(unsummed,{38:0,39:9}),reason=5),dict(data=edit(unsummed,{16:0,17:50,38:0,39:30},True),reason=5),
            dict(data=edit(good,{16:0,17:27,38:0,39:7},True),reason=5),
            dict(data=edit(request,{15:2}),reason=8),dict(data=edit(request,{16:0x86,17:0xdd}),reason=8),
            dict(data=edit(request,{18:8}),reason=8),dict(data=edit(request,{19:16}),reason=8),
            dict(data=edit(request,{21:2}),reason=8),dict(data=edit(request,{22:4}),reason=5)]


def expect_drops(frames,max_frame,admitted=None):
    """Fate of each frame in arrival order: queue full, oversize, or the decoder's rejection reason."""
    reasons=[];full=long=0
    for index,frame in enumerate(frames):
        data=frame['data'] if isinstance(frame,dict) else frame;link=frame.get('link_error',False) if isinstance(frame,dict) else False
        if admitted is not None and index not in admitted:full+=1
        elif len(data)>max_frame:long+=1
        elif (reason:=decode(data,max_frame,link)[1]):reasons.append(reason)
    return dict(reasons=reasons,full=full,long=long)


def directed(max_frame):
    padding=bytearray(udp(b'p')[:-4]);padding[43:]=b'\x7e'*(len(padding)-43)
    return [arp(),edit(arp(),{i:LOCAL_MAC[i] for i in range(6)}),udp(b''),udp(b'odd'),udp(bytes(range(max_frame-46))),udp(b'zero',zero_checksum=True),
            zero_result_packet(),with_fcs(padding)]


def random_frames(max_frame,seed,count):
    rng=random.Random(seed)
    return [udp(bytes(rng.randrange(256) for _ in range(rng.randrange(max_frame-45))),
                source_port=2000+i,identification=rng.randrange(65536),zero_checksum=i%3==0) for i in range(count)]


def rows(frames,seed=17,mode='sequential',reset=None):
    """Independent RX drive: no ready is sampled. Mode fixes the admission test contract."""
    result=[];rng=random.Random(seed)
    def idle(count,rst=1,ready=1):result.extend([[rst,0,0,0,0,ready] for _ in range(count)])
    def send(frame,ready=1,gaps=False):
        data=frame['data'] if isinstance(frame,dict) else frame;bad=frame.get('link_error',False) if isinstance(frame,dict) else False
        at=frame.get('link_at',len(data)//2) if isinstance(frame,dict) else 0
        for i,value in enumerate(data):
            if gaps and rng.randrange(7)==0:idle(1,ready=ready)
            result.append([1,1,value,int(i==len(data)-1),int(bad and i==at%len(data)),ready])
    idle(3,rst=0,ready=0)
    if mode in ('swap-exact','swap-early'):
        # Three frames fill TX and both slots. Draining a 64-byte reply pops on the 65th ready row:
        # the fourth frame starts on that row (slot reused) or on the row before it (still full).
        for frame in frames[:3]:send(frame,ready=0)
        idle(8,ready=0);idle(64 if mode=='swap-exact' else 63);send(frames[3]);idle(1500)
        return result
    if reset=='receive':
        for value in bytes(frames[0])[:20]:result.append([1,1,value,0,0,0])
        idle(3,rst=0,ready=0)
    elif reset=='transmit':
        send(frames[0],ready=0);idle(8,ready=0);idle(3,rst=0,ready=0)
    for frame in frames:
        send(frame,ready=0 if mode!='sequential' else 1,gaps=mode=='sequential')
        if mode=='sequential':idle(4*max(len(frame.get('data',b'')) if isinstance(frame,dict) else len(frame),64)+20)
    if mode=='overflow':
        # One TX slot plus two complete RX slots: the fourth and fifth frames are lost.
        for row in result:
            if row[0]:row[5]=0
    elif mode=='recover':
        # All five frames are 64 bytes. A slot opens halfway through the fourth;
        # it must still be discarded, while the fifth can be admitted.
        for i,row in enumerate(result):
            if row[0]:row[5]=int(i>=3+160)
    idle(1500)
    return result
