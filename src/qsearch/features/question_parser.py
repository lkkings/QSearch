"""Question structure parser to extract stem and options from OCR text.

Parses multiple choice question format using regex patterns.
"""

import re
from typing import Dict, List, Optional, Tuple


class QuestionParser:
    """Parses question structure from OCR text."""

    # Common option prefixes
    OPTION_PATTERNS = [
        r'^([A-D])[.)、]?\s*(.+)$',  # A. text, A) text, A、text
        r'^[(（]([A-D])[)）]\s*(.+)$',  # (A) text, (A)text
        r'^选项\s*([A-D])[.)、]?\s*(.+)$',  # 选项A. text
    ]

    def __init__(self):
        """Initialize parser with compiled patterns."""
        self.option_patterns = [re.compile(p, re.MULTILINE | re.IGNORECASE) for p in self.OPTION_PATTERNS]

    def parse(self, text: str) -> Dict[str, any]:
        """Parse question text into structured format.

        Args:
            text: OCR extracted text

        Returns:
            Dictionary with keys: stem, options, question_type, parse_success
        """
        if not text or not text.strip():
            return {
                'stem': '',
                'options': {},
                'question_type': 'unknown',
                'parse_success': False
            }

        lines = text.strip().split('\n')

        # Try to extract options
        options, option_lines = self._extract_options(lines)

        # Everything before options is the stem
        if option_lines:
            stem_lines = lines[:option_lines[0]]
        else:
            # No options found - entire text is stem
            stem_lines = lines

        stem = '\n'.join(stem_lines).strip()

        # Determine question type
        question_type = self._detect_question_type(stem, options)

        return {
            'stem': stem,
            'options': options,
            'question_type': question_type,
            'parse_success': len(options) > 0 if question_type == 'multiple_choice' else len(stem) > 0
        }

    def _extract_options(self, lines: List[str]) -> Tuple[Dict[str, str], List[int]]:
        """Extract multiple choice options from text lines.

        Args:
            lines: List of text lines

        Returns:
            Tuple of (options dict, list of line indices containing options)
        """
        options = {}
        option_line_indices = []

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            # Try each option pattern
            for pattern in self.option_patterns:
                match = pattern.match(line)
                if match:
                    option_label = match.group(1).upper()
                    option_text = match.group(2).strip()
                    options[option_label] = option_text
                    option_line_indices.append(i)
                    break

        return options, option_line_indices

    def _detect_question_type(self, stem: str, options: Dict[str, str]) -> str:
        """Detect question type from stem and options.

        Args:
            stem: Question stem text
            options: Extracted options

        Returns:
            Question type: 'multiple_choice', 'fill_in_blank', 'short_answer', 'essay', 'unknown'
        """
        if len(options) >= 2:
            return 'multiple_choice'

        # Check for fill-in-blank patterns
        if '____' in stem or '___' in stem or '（）' in stem or '()' in stem:
            return 'fill_in_blank'

        # Check for short answer indicators (Chinese and English)
        short_answer_keywords = [
            '简答', '简要', '简述', '回答',
            'answer briefly', 'short answer', 'explain'
        ]
        stem_lower = stem.lower()
        if any(keyword in stem_lower for keyword in short_answer_keywords):
            return 'short_answer'

        # Check for essay indicators
        essay_keywords = [
            '论述', '分析', '评价', '讨论',
            'discuss', 'analyze', 'evaluate', 'essay'
        ]
        if any(keyword in stem_lower for keyword in essay_keywords):
            return 'essay'

        return 'unknown'

    def extract_formulas(self, text: str) -> List[str]:
        """Extract potential mathematical formulas from text.

        Args:
            text: Input text

        Returns:
            List of extracted formula strings
        """
        formulas = []

        # Look for LaTeX-style formulas
        latex_pattern = r'\$([^\$]+)\$'
        formulas.extend(re.findall(latex_pattern, text))

        # Look for common math symbols and patterns
        math_patterns = [
            r'[a-zA-Z]\s*[+\-*/=]\s*[a-zA-Z0-9]',  # Simple equations: x + y
            r'\d+\s*[+\-*/=]\s*\d+',  # Numeric expressions: 2 + 2
            r'[a-zA-Z]\^[0-9]',  # Exponents: x^2
            r'√\d+',  # Square roots: √4
            r'∫|∑|∏|∂|∇',  # Calculus symbols
        ]

        for pattern in math_patterns:
            matches = re.findall(pattern, text)
            formulas.extend(matches)

        return formulas

    def normalize_option_labels(self, options: Dict[str, str]) -> Dict[str, str]:
        """Normalize option labels to standard format.

        Args:
            options: Dictionary of options

        Returns:
            Dictionary with normalized labels (A, B, C, D)
        """
        normalized = {}

        for label, text in options.items():
            # Ensure label is uppercase single letter
            label_clean = label.upper().strip()
            if len(label_clean) == 1 and label_clean.isalpha():
                normalized[label_clean] = text

        return normalized

    def is_valid_question(self, parsed: Dict[str, any]) -> bool:
        """Check if parsed question is valid.

        Args:
            parsed: Parsed question dictionary

        Returns:
            True if question has valid structure
        """
        if not parsed['parse_success']:
            return False

        # Must have non-empty stem
        if not parsed['stem'] or len(parsed['stem'].strip()) < 5:
            return False

        # Multiple choice must have at least 2 options
        if parsed['question_type'] == 'multiple_choice':
            return len(parsed['options']) >= 2

        return True
