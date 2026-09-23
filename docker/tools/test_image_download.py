import importlib.machinery
import importlib.util
import pathlib
import tempfile
import threading
import unittest

from PIL import Image


MODULE_PATH = pathlib.Path(__file__).with_name("image-download")
LOADER = importlib.machinery.SourceFileLoader("image_download", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
image_download = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(image_download)


class ImageMatchTest(unittest.TestCase):
    def setUp(self):
        self.target = Image.new("RGB", (40, 60), "#234b72")
        for x in range(8, 32):
            for y in range(12, 48):
                self.target.putpixel((x, y), (230, 180, 40))

    def test_returns_only_visually_matching_image_row(self):
        screenshot = Image.new("RGB", (800, 600), "#eeeeee")
        screenshot.paste(self.target.resize((80, 120)), (180, 350))
        rows = [
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 120, "width": 600, "height": 150}},
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 330, "width": 600, "height": 160}},
        ]

        match = image_download.find_unique_match(screenshot, self.target, rows)

        self.assertEqual(match["row"], rows[1])
        self.assertTrue(180 <= match["x"] <= 260)
        self.assertTrue(350 <= match["y"] <= 470)

    def test_rejects_ambiguous_visual_matches(self):
        screenshot = Image.new("RGB", (800, 600), "#eeeeee")
        screenshot.paste(self.target.resize((80, 120)), (180, 130))
        screenshot.paste(self.target.resize((80, 120)), (180, 350))
        rows = [
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 110, "width": 600, "height": 150}},
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 330, "width": 600, "height": 160}},
        ]

        with self.assertRaisesRegex(image_download.DownloadError, "IMAGE_IDENTITY_AMBIGUOUS"):
            image_download.find_unique_match(screenshot, self.target, rows)

    def test_rejects_rows_outside_the_safe_message_viewport(self):
        screenshot = Image.new("RGB", (800, 600), "#eeeeee")
        screenshot.paste(self.target.resize((80, 120)), (180, 10))
        rows = [
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": -5, "width": 600, "height": 150}},
        ]

        with self.assertRaisesRegex(image_download.DownloadError, "IMAGE_CARD_NOT_FOUND"):
            image_download.find_unique_match(screenshot, self.target, rows)

    def test_clicks_image_content_not_center_of_full_width_message_row(self):
        row = {"bounds": {"x": 423, "y": 472, "width": 704, "height": 121}}

        point = image_download.image_click_point(row)

        self.assertGreaterEqual(point["x"], 492)
        self.assertLessEqual(point["x"], 741)
        self.assertGreaterEqual(point["y"], 499)
        self.assertLessEqual(point["y"], 580)


class NativeImageSaveTest(unittest.TestCase):
    def test_native_path_is_bound_to_source_file_hash(self):
        stem = "b" * 32
        directory = pathlib.Path("/home/wechat/xwechat_files/account/msg/attach/" + "a" * 32 + "/2026-09/Img")
        self.assertEqual(
            image_download.native_image_path(directory, stem),
            pathlib.Path(f"/home/wechat/xwechat_files/account/temp/ImageUtils/{stem}_h.jpg"),
        )

    def test_missing_native_image_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(image_download.DownloadError, "IMAGE_NATIVE_DECODE_MISSING"):
                image_download.native_image_size(pathlib.Path(directory) / "missing.jpg", timeout_seconds=0)

    def test_publishes_only_the_matching_native_image(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            stem = "a" * 32
            source = folder / f"{stem}_h.jpg"
            other = folder / f"{'b' * 32}_h.jpg"
            Image.new("RGB", (80, 60), "#19a7c0").save(source, "JPEG")
            Image.new("RGB", (80, 60), "#ff0000").save(other, "JPEG")
            target = folder / f"{stem}_preview.jpg"

            size = image_download.publish_native_image(source, folder, stem, 24, target)

            self.assertEqual(size, source.stat().st_size)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertNotEqual(target.read_bytes(), other.read_bytes())
            with self.assertRaisesRegex(image_download.DownloadError, "IMAGE_IDENTITY_MISMATCH"):
                image_download.publish_native_image(other, folder, stem, 24, target)

    def test_waits_for_native_high_resolution_image_after_opening_viewer(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            stem = "a" * 32
            source = folder / f"{stem}_h.jpg"
            target = folder / f"{stem}_preview.jpg"
            timer = threading.Timer(0.1, lambda: Image.new("RGB", (581, 194), "white").save(source, "JPEG"))
            timer.start()
            try:
                size = image_download.publish_native_image(
                    source, folder, stem, 26, target, timeout_seconds=2
                )
            finally:
                timer.join()

            self.assertGreater(size, 0)
            with Image.open(target) as image:
                self.assertEqual(image.size, (581, 194))

    def test_recognizes_selected_chat(self):
        tree = {"children": [
            {"role": "list-item", "name": "群测试 小晖Allen: [Photo]", "states": ["SELECTED"]},
            {"role": "list-item", "name": "其他群 [Photo]", "states": []},
        ]}
        self.assertTrue(image_download.selected_chat(tree, "群测试"))
        self.assertFalse(image_download.selected_chat(tree, "其他群"))

    def test_publishes_native_export_for_current_high_resolution_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            source = folder / "image-a_export_22.jpg"
            original = Image.new("RGB", (568, 568), "#19a7c0")
            original.save(source, "JPEG")
            target = folder / "image-a_preview.jpg"

            image_download.publish_saved_image(source, target)

            self.assertFalse(source.exists())
            self.assertEqual(target.read_bytes(), (folder / "image-a_h_preview.jpg").read_bytes())


if __name__ == "__main__":
    unittest.main()
