"""
Unit tests for sign-up sheet image optimization.
Tests the optimize_image_for_storage function used during sign-up sheet uploads.
"""
import os
import tempfile
import pytest
from unittest.mock import patch
from PIL import Image

from app.utils.image_processing import optimize_image_for_storage


@pytest.mark.unit
class TestOptimizeImageForStorage:
    """Tests for optimize_image_for_storage()"""

    def _create_test_image(self, width: int, height: int, color: str = "red") -> str:
        """Create a temporary test image and return its path."""
        img = Image.new("RGB", (width, height), color)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        img.save(tmp.name, format="JPEG", quality=95)
        tmp.close()
        return tmp.name

    def test_large_image_is_resized(self):
        """Images larger than max_size should be resized down."""
        path = self._create_test_image(4000, 3000)
        try:
            result = optimize_image_for_storage(path, max_size=2048)
            assert result != path
            assert os.path.exists(result)
            img = Image.open(result)
            assert img.width <= 2048
            assert img.height <= 2048
        finally:
            os.unlink(path)
            if os.path.exists(result):
                os.unlink(result)

    def test_small_image_not_upscaled(self):
        """Images smaller than max_size should not be upscaled."""
        path = self._create_test_image(800, 600)
        try:
            result = optimize_image_for_storage(path, max_size=2048)
            assert os.path.exists(result)
            img = Image.open(result)
            assert img.width == 800
            assert img.height == 600
        finally:
            os.unlink(path)
            if os.path.exists(result):
                os.unlink(result)

    def test_rgba_converted_to_rgb(self):
        """RGBA images should be converted to RGB for JPEG output."""
        img = Image.new("RGBA", (500, 500), (255, 0, 0, 128))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        img.save(tmp.name, format="PNG")
        tmp.close()
        try:
            result = optimize_image_for_storage(tmp.name)
            assert os.path.exists(result)
            output = Image.open(result)
            assert output.mode == "RGB"
        finally:
            os.unlink(tmp.name)
            if os.path.exists(result):
                os.unlink(result)

    def test_returns_original_on_error(self):
        """Should return original path if processing fails."""
        result = optimize_image_for_storage("/nonexistent/path.jpg")
        assert result == "/nonexistent/path.jpg"

    def test_quality_parameter(self):
        """Lower quality should produce a smaller file."""
        path = self._create_test_image(2000, 1500)
        try:
            high_q = optimize_image_for_storage(path, quality=95)
            # Create another copy for low quality test
            path2 = self._create_test_image(2000, 1500)
            low_q = optimize_image_for_storage(path2, quality=50)
            assert os.path.getsize(low_q) < os.path.getsize(high_q)
        finally:
            for p in [path, path2, high_q, low_q]:
                if os.path.exists(p):
                    os.unlink(p)
