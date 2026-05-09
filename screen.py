import cv2
import numpy as np
import pyautogui
import time
from config import CLICK_DELAY, IMAGE_DIR, TEMPLATE_THRESHOLD
import os

pyautogui.FAILSAFE = True


def take_screenshot(region=None):
    if region is not None:
        pil_image = pyautogui.screenshot(region=region)
    else:
        pil_image = pyautogui.screenshot()
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def find_template(template_path, screenshot=None, threshold=0.8):
    full_path = os.path.join(IMAGE_DIR, template_path)
    if not os.path.exists(full_path):
        return []
    template = cv2.imread(full_path)
    if template is None:
        return []
    if screenshot is None:
        screenshot = take_screenshot()
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    h, w = template.shape[:2]
    locations = np.where(result >= threshold)
    matches = []
    for pt in zip(*locations[::-1]):
        score = result[pt[1], pt[0]]
        matches.append((pt[0], pt[1], w, h, score))
    if not matches:
        return []
    matches.sort(key=lambda m: m[4], reverse=True)
    kept = []
    for match in matches:
        x, y, mw, mh, score = match
        suppress = False
        for kept_match in kept:
            kx, ky, kw, kh, _ = kept_match
            if abs(x - kx) < mw and abs(y - ky) < mh:
                suppress = True
                break
        if not suppress:
            kept.append(match)
    return [(x, y, w, h) for x, y, w, h, _ in kept]


def find_and_click(template_path, threshold=0.8):
    matches = find_template(template_path, threshold=threshold)
    if not matches:
        return False
    x, y, w, h = matches[0]
    center_x = x + w // 2
    center_y = y + h // 2
    pyautogui.click(center_x, center_y)
    time.sleep(CLICK_DELAY)
    return True


def wait_for(template_path, timeout=10.0, interval=0.5, threshold=0.8):
    start = time.time()
    while time.time() - start < timeout:
        if find_and_click(template_path, threshold=threshold):
            return True
        time.sleep(interval)
    return False


def click_position(x, y):
    pyautogui.click(x, y)
    time.sleep(CLICK_DELAY)
