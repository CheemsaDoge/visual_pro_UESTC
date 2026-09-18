#!/usr/bin/env python3
"""Unit tests for managed stitch-input deletion."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from app import config
from app.services.storage_service import delete_stitch_input_images


class DeleteStitchInputImagesTest(unittest.TestCase):
    def test_deletes_only_selected_allowed_files(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(config, "STITCH_INPUT_DIR", tmpdir):
            for name in ("left.jpg", "right.png", ".gitkeep"):
                with open(os.path.join(tmpdir, name), "wb") as file_obj:
                    file_obj.write(b"test")

            result = delete_stitch_input_images(["left.jpg", "right.png", "left.jpg"])

            self.assertTrue(result["ok"])
            self.assertEqual(result["deleted_count"], 2)
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "left.jpg")))
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "right.png")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, ".gitkeep")))

    def test_rejects_path_traversal_without_deleting_files(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(config, "STITCH_INPUT_DIR", tmpdir):
            image_path = os.path.join(tmpdir, "keep.jpg")
            with open(image_path, "wb") as file_obj:
                file_obj.write(b"test")

            result = delete_stitch_input_images(["../keep.jpg"])

            self.assertFalse(result["ok"])
            self.assertEqual(result["deleted_count"], 0)
            self.assertTrue(os.path.exists(image_path))


if __name__ == "__main__":
    unittest.main()
