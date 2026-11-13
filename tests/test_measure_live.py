import email
import unittest

from scripts.measure_live import multipart, summary


class MeasureLiveTests(unittest.TestCase):
    def test_multipart_round_trips_fields_and_file(self):
        body, ctype = multipart({'language': 'english', 'demo_acknowledged': 'true'}, 'file', 'clip.mp3', b'\x00\xffdata')
        message = email.message_from_bytes(b'Content-Type: ' + ctype.encode() + b'\r\n\r\n' + body)
        parts = {p.get_param('name', header='content-disposition'): p for p in message.get_payload()}
        self.assertEqual(parts['language'].get_payload(), 'english')
        self.assertEqual(parts['demo_acknowledged'].get_payload(), 'true')
        self.assertEqual(parts['file'].get_filename(), 'clip.mp3')
        self.assertEqual(parts['file'].get_content_type(), 'audio/mpeg')
        self.assertEqual(parts['file'].get_payload(decode=True), b'\x00\xffdata')

    def test_summary_percentiles(self):
        self.assertEqual(summary([3, 1, 2]), {'n': 3, 'min': 1, 'p50': 2, 'p95': 3, 'max': 3})


if __name__ == '__main__':
    unittest.main()
