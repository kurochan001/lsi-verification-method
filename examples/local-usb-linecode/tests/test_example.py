from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, simulate_vectors
from system_test_support import SystemContract

P = load_example('local-usb-linecode')


class UsbTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-usb-linecode'
    GOALS = 9

    def test_published_usbif_token_crc_vectors(self):
        for fields, crc in [(0x710, '10100'), (0x001, '10111'), (0x3a + (0xa << 7), '11100')]:
            self.assertEqual(P.crc_bits(P.least_first(fields, 11), 5), list(map(int, crc)))

    def test_data_crc16_check_value(self):
        payload = [b for octet in b'123456789' for b in P.least_first(octet, 8)]
        self.assertEqual(P.crc_bits(payload, 16), P.least_first(0xb4c8, 16))

    def test_stuff_before_eop(self):
        # This token ends its CRC with six ones on the wire.
        token = next(v for v in range(2048) if P.stuffed_bits(1, P.least_first(v, 11), 5)[-1][1] == P.STUFF)
        rows = [[0]*6] + P.frame(0, 1, token, 2)
        sim = simulate_vectors(P, rows)
        self.assertEqual(sim.returncode, 0, sim.stdout)

    def test_wrong_payload_bit_is_detected_at_the_receiver(self):
        rows = [[0]*6] + P.frame(1, 3, 0x80, 1)
        rows[-1][2] ^= 1
        sim = simulate_vectors(P, rows, {'PKT': 1})
        self.assertNotEqual(sim.returncode, 0)
        self.assertIn('CHECK_FAIL USB_LINE', sim.stdout)
