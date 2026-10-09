import unittest

from script.block_windows import block_windows


class TestBlockWindows(unittest.TestCase):
    def test_single_block(self):
        self.assertEqual(block_windows(100, 100), [(100, 100)])

    def test_exactly_10000_blocks(self):
        self.assertEqual(block_windows(1, 10_000), [(1, 10_000)])

    def test_10001_blocks(self):
        self.assertEqual(block_windows(1, 10001), [(1, 10000), (10001, 10001)])

    def test_start_after_end(self):
        self.assertEqual(block_windows(106, 100), [])

    def test_reject_invalid_max_blocks(self):
        for size in (0, -1):
            with self.subTest(size=size):
                with self.assertRaisesRegex(
                    ValueError, 
                    r"^max_blocks must be positive$"
                ):
                    block_windows(100, 106, size)

    def test_complete_coverage(self):
        start, end, size = 100, 106, 3

        windows = block_windows(start, end, size)

        self.assertEqual(windows[0][0], start)
        self.assertEqual(windows[-1][1], end)

        total = 0
        next_start = start

        for first, last in windows:
            self.assertEqual(first, next_start)
            self.assertLessEqual(first, last)
            self.assertLessEqual(last - first + 1, size)

            total += last - first + 1
            next_start = last + 1

        self.assertEqual(total, end - start + 1)

