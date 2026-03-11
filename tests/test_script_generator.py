import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import unittest

from script_generator import ScenePlan, ScriptGenerator


class TestScriptGenerator(unittest.TestCase):
    def test_target_scene_count(self):
        gen = ScriptGenerator()
        self.assertEqual(gen._target_scene_count(1, 8), 7)

    def test_parse_ollama_output(self):
        gen = ScriptGenerator()
        output = 'prefix {"scenes": [{"narration": "n1", "visual_description": "v1"}]} suffix'
        parsed = gen._parse_ollama_output(output)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0], ScenePlan(index=1, narration='n1', visual_description='v1'))


if __name__ == '__main__':
    unittest.main()
