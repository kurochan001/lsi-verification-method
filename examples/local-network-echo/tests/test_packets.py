import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('packet_tests',HERE/'support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
M=S.MODEL


class PacketTests(unittest.TestCase):
    def test_crc32_check_vector_and_wire_order(self):self.assertEqual(M.with_fcs(b'123456789')[-4:],bytes.fromhex('2639f4cb'))
    def test_internet_checksum_known_vector(self):self.assertEqual(M.checksum(bytes.fromhex('0001f203f4f5f6f7')),0x220d)
    def test_odd_checksum_zero_padding(self):self.assertEqual(M.checksum(b'\x01\x02\x03'),0xfbfd)
    def test_arp_fields_and_minimum_padding(self):
        reply,reason,kind=M.decode(M.arp());self.assertEqual((reason,kind,len(reply)),(0,1,64))
        self.assertEqual(reply[:12],M.PEER_MAC+M.LOCAL_MAC);self.assertEqual(reply[20:22],b'\0\2');self.assertEqual(reply[42:60],bytes(18))
    def test_udp_swaps_endpoints_preserves_payload_and_recalculates_checksums(self):
        reply,reason,kind=M.decode(M.udp(b'abc'));self.assertEqual((reason,kind),(0,2));self.assertEqual(reply[42:45],b'abc')
        self.assertEqual(reply[26:34],M.LOCAL_IP+M.PEER_IP);self.assertEqual(reply[34:38],struct.pack('!HH',M.PORT,2468))
        self.assertEqual(M.checksum(reply[14:34]),0);self.assertEqual(M.checksum(reply[26:34]+struct.pack('!BBH',0,17,11)+reply[34:45]),0)
    def test_zero_udp_checksum_is_accepted_but_reply_has_checksum(self):
        reply,reason,_=M.decode(M.udp(b'zero',zero_checksum=True));self.assertEqual(reason,0);self.assertNotEqual(reply[40:42],b'\0\0')
    def test_computed_zero_udp_checksum_is_transmitted_as_ffff(self):self.assertEqual(M.decode(M.zero_result_packet())[0][40:42],b'\xff\xff')
    def test_invalid_frames_have_declared_reasons(self):
        for limit in (96,128):
            for frame in M.invalid_frames(limit):
                with self.subTest(limit=limit,reason=frame['reason']):self.assertEqual(M.decode(frame['data'],limit,frame.get('link_error',False))[1],frame['reason'])
    def test_each_added_frame_is_rejected_by_one_term_only(self):
        good=M.udp(b'odd');self.assertEqual(M.decode(M.edit(good,{23:17},True))[1],0)
        for changes,reason in (({23:6},8),({12:0x86,13:0xdd},8),({i:255 for i in range(6)},4)):
            self.assertEqual(M.decode(M.edit(good,changes,bool(23 in changes)))[1],reason)
        lenient=M.udp(b'odd',zero_checksum=True)
        self.assertEqual(M.decode(M.edit(lenient,{38:0,39:9}))[1],5)
        self.assertEqual(M.decode(M.edit(lenient,{16:0,17:50,38:0,39:30},True))[1],5)
        request=M.arp();self.assertEqual(M.decode(request)[1],0)
        for changes,reason in (({15:2},8),({16:0x86},8),({18:8},8),({19:16},8),({21:2},8),({22:4},5)):
            self.assertEqual(M.decode(M.edit(request,changes))[1],reason)
    def test_drop_expectations_separate_queue_length_and_decoder_fates(self):
        good=M.udp(b'odd');bad=bytearray(good);bad[-1]^=1
        self.assertEqual(M.expect_drops([good,bytes(bad),M.with_fcs(bytes(96))],96),dict(reasons=[1],full=0,long=1))
        self.assertEqual(M.expect_drops([good,bytes(bad)],96,admitted=(0,)),dict(reasons=[],full=1,long=0))
    def test_link_error_position_follows_the_frame_request(self):
        good=M.udp(b'odd');n=len(good)
        for at,position in ((0,0),(-1,n-1),(None,n//2)):
            frame=dict(data=good,link_error=True,reason=3)
            if at is not None:frame['link_at']=at
            rows=[r for r in M.rows([frame],mode='overflow') if r[1]];self.assertEqual([i for i,r in enumerate(rows) if r[4]],[position])
    def test_swap_rows_start_the_fourth_frame_on_or_before_the_pop_row(self):
        frames=[M.udp(bytes((i,1,2))) for i in range(4)]
        starts=[next(i for i,r in enumerate(M.rows(frames,mode=mode)) if i>3+3*64 and r[1]) for mode in ('swap-exact','swap-early')]
        self.assertEqual(starts[0]-starts[1],1);self.assertEqual(starts[0],3+3*64+8+64)
    def test_directed_frames_include_unicast_arp(self):
        unicast=M.directed(96)[1];self.assertEqual(unicast[:6],M.LOCAL_MAC);self.assertEqual(M.decode(unicast)[1:],(0,1))
    def test_maximum_payload_and_frame_limit(self):
        for limit in (96,128):
            f=M.udp(bytes(range(limit-46)));self.assertEqual(len(f),limit);self.assertEqual(len(M.decode(f,limit)[0]),limit)
            self.assertEqual(M.decode(f,limit-1)[1],2)
    def test_padding_is_not_udp_payload(self):
        f=M.directed(96)[-1];reply=M.decode(f)[0];self.assertEqual(reply[42:43],b'p');self.assertEqual(reply[43:60],bytes(17))
    def test_link_error_precedes_length_and_crc(self):self.assertEqual(M.decode(b'bad',link_error=True)[1],3)
    def test_bad_fcs_precedes_destination_filter(self):
        f=bytearray(M.udp());f[0]^=1;self.assertEqual(M.decode(f)[1],1)
    def test_source_mac_mismatch_is_rejected(self):self.assertEqual(M.decode(M.edit(M.arp(),{22:4}))[1],5)
    def test_random_reproducibility(self):self.assertEqual(M.random_frames(128,17,3),M.random_frames(128,17,3));self.assertNotEqual(M.random_frames(128,17,3),M.random_frames(128,18,3))


class CompletionTests(unittest.TestCase):
    def test_missing_or_extra_completion_counts_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            d=Path(name);S.validate_case(d,{'tx_frames':1},{'tx_frames':1})
            for counts in ({},{'tx_frames':0},{'tx_frames':1,'extra':1}):
                with self.assertRaises(ValueError):S.validate_case(d,{'tx_frames':1},counts)
    def test_ram_and_retirement_trace_are_required_for_soc(self):
        with tempfile.TemporaryDirectory() as name:
            d=Path(name);(d/'ram-readback.hex').write_text('00000001\n00000002\n');(d/'retirement.log').write_text('retired\n')
            S.validate_case(d,{}, {},True,[bytes((1,2))])
            for data in ('00000001\n','00000101\n00000002\n','00000001\n00000003\n'):
                (d/'ram-readback.hex').write_text(data)
                with self.assertRaises(ValueError):S.validate_case(d,{}, {},True,[bytes((1,2))])
            (d/'ram-readback.hex').write_text('00000001\n00000002\n');(d/'retirement.log').write_text('')
            with self.assertRaisesRegex(ValueError,'retirement'):S.validate_case(d,{}, {},True,[bytes((1,2))])
if __name__=='__main__':unittest.main()
