import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validator"))
sys.path.insert(0, str(ROOT / "scripts"))
import pngutil  # noqa: E402
from validate import generate_candidates  # noqa: E402


class CandidateGenerationTest(unittest.TestCase):
    def run_candidate_case(self, boxes, segment_category, segment_rect):
        with tempfile.TemporaryDirectory() as tmp:
            delivery = Path(tmp)
            (delivery / "labels").mkdir()
            (delivery / "masks").mkdir()
            (delivery / "classes.txt").write_text("0 car\n1 truck\n", encoding="utf-8")
            (delivery / "labels" / "sample.txt").write_text(
                "\n".join(boxes) + ("\n" if boxes else ""),
                encoding="utf-8",
            )
            (delivery / "manifest.json").write_text(
                json.dumps({"items": {"sample": {
                    "label": "labels/sample.txt",
                    "mask": "masks/sample.png",
                }}}),
                encoding="utf-8",
            )
            (delivery / "panoptic.json").write_text(json.dumps({
                "categories": [
                    {"id": 3, "name": "car", "isthing": 1},
                    {"id": 4, "name": "truck", "isthing": 1},
                ],
                "images": [{"file_name": "sample.jpg", "width": 100, "height": 100}],
                "annotations": [{
                    "file_name": "sample.png",
                    "segments_info": [{
                        "id": 17,
                        "category_id": segment_category,
                        "iscrowd": 0,
                        "bbox": [
                            segment_rect[0],
                            segment_rect[1],
                            segment_rect[2] - segment_rect[0],
                            segment_rect[3] - segment_rect[1],
                        ],
                    }],
                }],
            }), encoding="utf-8")
            pixels = bytearray(100 * 100 * 3)
            x1, y1, x2, y2 = segment_rect
            rgb = bytes(pngutil.segment_rgb(17))
            for y in range(y1, y2):
                for x in range(x1, x2):
                    offset = (y * 100 + x) * 3
                    pixels[offset:offset + 3] = rgb
            pngutil.write_rgb(delivery / "masks" / "sample.png", 100, 100, pixels)
            return generate_candidates(delivery, [])

    def test_class_disagreement_flags_both_sources_for_visual_review(self):
        candidates = self.run_candidate_case(
            ["0 0.5 0.5 0.6 0.6"], 4, (30, 30, 70, 70)
        )
        self.assertEqual(
            {(row["type"], row["target"]) for row in candidates},
            {("class_swap", "sample"), ("category_swap", "sample")},
        )

    def test_large_segment_without_detection_box_is_candidate(self):
        candidates = self.run_candidate_case([], 3, (20, 20, 80, 80))
        self.assertEqual(candidates, [{"type": "missing_box", "target": "sample"}])

    def test_one_segment_overlapping_two_same_class_boxes_is_merge_candidate(self):
        candidates = self.run_candidate_case(
            ["0 0.35 0.5 0.4 0.4", "0 0.65 0.5 0.4 0.4"],
            3,
            (20, 30, 80, 70),
        )
        self.assertIn(
            {"type": "instance_merge", "target": "sample"},
            candidates,
        )

    def test_partial_mask_coverage_is_drift_candidate(self):
        candidates = self.run_candidate_case(
            ["0 0.4 0.5 0.2 0.4"], 3, (20, 30, 60, 70)
        )
        self.assertIn({"type": "bbox_drift", "target": "sample"}, candidates)


if __name__ == "__main__":
    unittest.main()
