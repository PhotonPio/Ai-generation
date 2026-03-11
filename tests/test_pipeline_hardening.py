import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import json
import unittest

from main import app


class TestPipelineHardening(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health(self):
        resp = self.client.get('/health')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['ok'])

    def test_schema_check_valid(self):
        payload = {
            'raw_text': json.dumps({
                'scenes': [
                    {
                        'narration': 'A mountain landscape.',
                        'visual_description': 'Snowy peaks at dawn.',
                        'estimated_duration': 8,
                    }
                ]
            }),
            'minutes': 1,
            'scene_seconds': 8,
        }
        resp = self.client.post('/schema-check', json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['ok'])
        self.assertGreaterEqual(len(data['scenes']), 1)
        self.assertIn('estimated_duration', data['scenes'][0])


if __name__ == '__main__':
    unittest.main()
