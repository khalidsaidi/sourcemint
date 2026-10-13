

def block_windows(start, end, max_blocks=10_000):
    if(max_blocks <= 0):
        raise ValueError("max_blocks must be positive")

    windows = []
    current = start

    while current <= end:
        windows_end = min(current + max_blocks - 1, end)
        windows.append((current, windows_end))
        current = windows_end + 1

    return windows

if __name__ == "__main__":
    result = block_windows(100, 106, 3)
    assert result == [(100, 102), (103, 105), (106, 106)]
    print(result)