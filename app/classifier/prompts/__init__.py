"""Versioned classifier prompt contracts."""

from app.classifier.prompts.stage1_v2 import STAGE1_PROMPT_VERSION, STAGE1_SYSTEM_PROMPT
from app.classifier.prompts.stage2_v2 import STAGE2_PROMPT_VERSION, STAGE2_SYSTEM_PROMPT

__all__ = [
    "STAGE1_PROMPT_VERSION",
    "STAGE1_SYSTEM_PROMPT",
    "STAGE2_PROMPT_VERSION",
    "STAGE2_SYSTEM_PROMPT",
]
