"""Text normalization functions for consistent matching.

Provides various normalization strategies for text, options, and formulas.
"""

import re
import unicodedata
from typing import List


def remove_whitespace(text: str) -> str:
    """Remove all whitespace from text.

    Args:
        text: Input text

    Returns:
        Text with whitespace removed
    """
    return ''.join(text.split())


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace to single spaces.

    Args:
        text: Input text

    Returns:
        Text with normalized whitespace
    """
    return ' '.join(text.split())


def normalize_punctuation(text: str) -> str:
    """Normalize punctuation marks.

    Converts Chinese punctuation to ASCII equivalents.

    Args:
        text: Input text

    Returns:
        Text with normalized punctuation
    """
    replacements = {
        '，': ',',
        '。': '.',
        '！': '!',
        '？': '?',
        '：': ':',
        '；': ';',
        '（': '(',
        '）': ')',
        '【': '[',
        '】': ']',
        '、': ',',
        '"': '"',
        '"': '"',
        ''': "'",
        ''': "'",
    }

    normalized = text
    for chinese, ascii_char in replacements.items():
        normalized = normalized.replace(chinese, ascii_char)

    return normalized


def remove_punctuation(text: str) -> str:
    """Remove all punctuation from text.

    Args:
        text: Input text

    Returns:
        Text without punctuation
    """
    # Remove ASCII punctuation
    text = re.sub(r'[^\w\s]', '', text)

    # Remove Chinese punctuation
    chinese_punct = '，。！？：；、""''（）【】'
    for char in chinese_punct:
        text = text.replace(char, '')

    return text


def normalize_unicode(text: str) -> str:
    """Normalize Unicode characters to NFC form.

    Args:
        text: Input text

    Returns:
        Unicode-normalized text
    """
    return unicodedata.normalize('NFC', text)


def to_lowercase(text: str) -> str:
    """Convert text to lowercase (handles ASCII only to preserve Chinese).

    Args:
        text: Input text

    Returns:
        Lowercase text
    """
    return text.lower()


def sort_text(text: str, delimiter: str = None) -> str:
    """Sort words/characters in text.

    Args:
        text: Input text
        delimiter: Delimiter to split on. None = split by character

    Returns:
        Text with sorted components
    """
    if delimiter is not None:
        parts = text.split(delimiter)
        parts.sort()
        return delimiter.join(parts)
    else:
        # Sort characters
        return ''.join(sorted(text))


def normalize_options(options: List[str], strategies: List[str]) -> List[str]:
    """Apply normalization strategies to option list.

    Args:
        options: List of option texts
        strategies: List of normalization strategies to apply

    Returns:
        List of normalized options
    """
    normalized = options.copy()

    for strategy in strategies:
        if strategy == 'remove_whitespace':
            normalized = [remove_whitespace(opt) for opt in normalized]
        elif strategy == 'normalize_whitespace':
            normalized = [normalize_whitespace(opt) for opt in normalized]
        elif strategy == 'normalize_punctuation':
            normalized = [normalize_punctuation(opt) for opt in normalized]
        elif strategy == 'remove_punctuation':
            normalized = [remove_punctuation(opt) for opt in normalized]
        elif strategy == 'lowercase':
            normalized = [to_lowercase(opt) for opt in normalized]
        elif strategy == 'sort':
            normalized = sorted(normalized)
        elif strategy == 'unicode':
            normalized = [normalize_unicode(opt) for opt in normalized]
        else:
            raise ValueError(f"Unknown normalization strategy: {strategy}")

    return normalized


def normalize_text(text: str, strategies: List[str]) -> str:
    """Apply normalization strategies to text.

    Args:
        text: Input text
        strategies: List of normalization strategies to apply

    Returns:
        Normalized text
    """
    normalized = text

    for strategy in strategies:
        if strategy == 'remove_whitespace':
            normalized = remove_whitespace(normalized)
        elif strategy == 'normalize_whitespace':
            normalized = normalize_whitespace(normalized)
        elif strategy == 'normalize_punctuation':
            normalized = normalize_punctuation(normalized)
        elif strategy == 'remove_punctuation':
            normalized = remove_punctuation(normalized)
        elif strategy == 'lowercase':
            normalized = to_lowercase(normalized)
        elif strategy == 'unicode':
            normalized = normalize_unicode(normalized)
        else:
            raise ValueError(f"Unknown normalization strategy: {strategy}")

    return normalized


def compare_normalized(text1: str, text2: str, strategies: List[str]) -> bool:
    """Compare two texts after applying normalization.

    Args:
        text1: First text
        text2: Second text
        strategies: Normalization strategies to apply

    Returns:
        True if normalized texts are equal
    """
    norm1 = normalize_text(text1, strategies)
    norm2 = normalize_text(text2, strategies)
    return norm1 == norm2


def normalize_formula(formula: str) -> str:
    """Normalize mathematical formula for comparison.

    Args:
        formula: LaTeX or text formula

    Returns:
        Normalized formula
    """
    if not formula:
        return ""

    normalized = formula.strip()

    # Remove extra whitespace
    normalized = ' '.join(normalized.split())

    # Normalize common math symbols
    replacements = {
        '×': '*',
        '÷': '/',
        '·': '*',
        '²': '^2',
        '³': '^3',
    }

    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    return normalized
