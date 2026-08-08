from __future__ import annotations

import hashlib
import hmac
import random
import time
from typing import Tuple

from app.core.config import get_settings


def create_math_captcha() -> Tuple[str, str]:
    """Return (question, signed_token)."""
    question, token, _answer = create_math_captcha_with_answer()
    return question, token


def create_math_captcha_with_answer() -> Tuple[str, str, str]:
    """Return (question, signed_token, answer) — useful for tests."""
    left = random.randint(1, 9)
    right = random.randint(1, 9)
    answer = left + right
    issued = int(time.time())
    payload = f"{left}+{right}={answer}:{issued}"
    signature = hmac.new(
        get_settings().secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"What is {left} + {right}?", f"{payload}:{signature}", str(answer)


def verify_math_captcha(token: str, user_answer: str, max_age_seconds: int = 600) -> bool:
    try:
        equation, issued_str, signature = token.rsplit(":", 2)
        payload = f"{equation}:{issued_str}"
        expected = hmac.new(
            get_settings().secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        if int(time.time()) - int(issued_str) > max_age_seconds:
            return False
        _, answer_str = equation.rsplit("=", 1)
        return int(user_answer.strip()) == int(answer_str)
    except (ValueError, TypeError):
        return False
