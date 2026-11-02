"""Educational frame contract; CRC by polynomial division, not an RTL bit loop."""
def crc8(data):
    data=bytes(data)
    value=(int.from_bytes(data,'big')<<8)^(0xff<<(8*len(data)))
    while value.bit_length()>8:value^=0x11d<<(value.bit_length()-9)
    return value^0xff

def frame(data_id,counter,payload):
    if not 0<=data_id<=0xffff or not 0<=counter<=255 or not 0<=payload<=0xffff:raise ValueError('frame field range')
    body=data_id.to_bytes(2,'big')+bytes([counter])+payload.to_bytes(2,'big')
    return (int.from_bytes(body,'big')<<8)|crc8(body)

class Guard:
    def __init__(self,data_id):
        if not 0<=data_id<=0xffff:raise ValueError('Data ID range')
        self.data_id=data_id;self.reset()
    def reset(self):self.expected=0;self.pending=None
    def ready(self,rst,flush,out_ready):return int(bool(rst and not flush and (self.pending is None or out_ready)))
    def step(self,rst,flush,valid,packet,out_ready):
        if any(v not in (0,1) for v in (rst,flush,valid,out_ready)) or not 0<=packet<2**48:raise ValueError('guard input range')
        ready=self.ready(rst,flush,out_ready);accepted=rejected=reason=0
        if not rst or flush:self.reset()
        else:
            if out_ready:self.pending=None
            if valid and ready:
                octets=packet.to_bytes(6,'big');counter=octets[2]
                if crc8(octets[:-1])!=octets[-1]:reason=1
                elif int.from_bytes(octets[:2],'big')!=self.data_id:reason=2
                elif counter!=self.expected:reason=3
                if reason:rejected=1
                else:self.pending=int.from_bytes(octets[3:5],'big');self.expected=(counter+1)%256;accepted=1
        return [ready,int(self.pending is not None),self.pending or 0,accepted,rejected,reason]
