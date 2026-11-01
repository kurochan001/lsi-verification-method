import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('image_test_support',HERE/'support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)


class OracleTests(unittest.TestCase):
    def test_constant_image_has_zero_interior_and_known_padded_edges(self):
        self.assertEqual(S.MODEL.sobel([12]*20,5,4),[72,48,48,48,72,48,0,0,0,48,48,0,0,0,48,72,48,48,48,72])

    def test_linear_ramp_has_known_signed_derivatives(self):
        image=[3*x+5*y for y in range(5) for x in range(5)]
        result=S.MODEL.sobel(image,5,5)
        for y in range(1,4):
            for x in range(1,4):self.assertEqual(result[y*5+x],64)

    def test_impulse_saturates_neighbours_but_not_the_zero_coefficient_centre(self):
        image=[0]*25;image[12]=255
        expected=[255 if abs(x-2)<=1 and abs(y-2)<=1 and (x,y)!=(2,2) else 0 for y in range(5) for x in range(5)]
        self.assertEqual(S.MODEL.sobel(image,5,5),expected)

    def test_invalid_shapes_and_samples_are_rejected(self):
        for values,w,h in (([0]*9,2,3),([0]*8,3,3),([256]*9,3,3),([-1]*9,3,3),([1.0]*9,3,3)):
            with self.subTest(w=w,h=h,values=values),self.assertRaises(ValueError):S.MODEL.sobel(values,w,h)

    def test_random_frames_are_reproducible_and_include_low_contrast(self):
        a=S.MODEL.random_frames(5,4,17,4)
        self.assertEqual(a,S.MODEL.random_frames(5,4,17,4));self.assertNotEqual(a,S.MODEL.random_frames(5,4,18,4))
        self.assertLess(max(a[0]),32);self.assertGreater(max(a[1]),31)

    def test_stream_completion_requires_acceptance_and_reset_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);counts=dict(pixels=2,frames=1,accepted=2,resets=1)
            S.validate_completion(d,[[0,1]],counts,1,False)
            for bad in (dict(counts,accepted=1),dict(counts,resets=0),dict(counts,extra=1)):
                with self.subTest(bad=bad),self.assertRaises(ValueError):S.validate_completion(d,[[0,1]],bad,1,False)


if __name__=='__main__':unittest.main()
