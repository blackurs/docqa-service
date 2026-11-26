"""Deterministic context retrieval (no external vector DB required).

Long documents do not fit into a prompt (and cost money), so the service first
selects the most question-relevant sentences. The ranking is a small TF-IDF
style lexical scorer:

* split the document into sentences;
* weight overlapping words by inverse sentence frequency;
* normalise by sentence length to avoid rewarding very long sentences;
* keep reading order of the selected excerpts.

The same excerpts are used as citations in the response and as the source of
the extractive fallback when the LLM is unavailable. Excerpts are returned in
relevance order (most relevant first), which keeps prompt numbering aligned
with citation numbers.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Sequence, Tuple

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n\s*\n+")
_BULLET_OR_HEADING_RE = re.compile(r"\n(?=\s*(?:[-*•–—]|\d+[.)]\s|#{1,6}\s))")
_SOFT_WRAP_RE = re.compile(r"(?<!\n)\n(?!\n)")
_WS_RE = re.compile(r"\s+")

_STOPWORDS = frozenset(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
    только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если
    уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей
    может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз
    тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом
    один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец
    два об другой хоть после над больше тот через эти нас про всего них какая много
    разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой
    им более всегда конечно всю между the a an and or of to in is are was were be been
    it its this that these those for on with as at by from not no but if then than so
    such do does did can could should would may might must will shall have has had
    """.split()
)


@dataclass(frozen=True)
class Excerpt:
    """A selected fragment of the source document."""

    index: int  # 1-based position in the returned list (used in citations)
    text: str
    score: float


def normalize_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def split_sentences(text: str) -> List[str]:
    """Split a document into reasonably sized sentences, preserving order.

    Hard-wrapped lines (a newline in the middle of a sentence) are joined, while
    blank lines, list items and markdown headings remain boundaries.
    """
    prepared = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    prepared = _BULLET_OR_HEADING_RE.sub("\n\n", prepared)
    prepared = _SOFT_WRAP_RE.sub(" ", prepared)

    sentences: List[str] = []
    for chunk in _SENTENCE_SPLIT_RE.split(prepared):
        sentence = normalize_whitespace(chunk)
        if len(sentence) >= 15:
            sentences.append(sentence)

    if not sentences:
        whole = normalize_whitespace(prepared)
        if whole:
            sentences.append(whole)
    return sentences


def _tokens(text: str) -> List[str]:
    return [
        token.lower()
        for token in _WORD_RE.findall(text)
        if len(token) > 1 and token.lower() not in _STOPWORDS
    ]


def rank_sentences(question: str, sentences: Sequence[str]) -> List[Tuple[int, float]]:
    """Return ``(sentence_position, score)`` pairs."""
    question_tokens = set(_tokens(question))
    tokenized = [_tokens(sentence) for sentence in sentences]
    total = max(len(sentences), 1)

    document_frequency: Counter = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))

    def idf(token: str) -> float:
        return math.log((total + 1) / (document_frequency.get(token, 0) + 1)) + 1.0

    scored: List[Tuple[int, float]] = []
    for position, tokens in enumerate(tokenized):
        if not tokens:
            scored.append((position, 0.0))
            continue
        unique = set(tokens)
        overlap = question_tokens & unique
        if not overlap:
            scored.append((position, 0.0))
            continue
        score = sum(idf(token) for token in overlap) / math.sqrt(len(unique))
        scored.append((position, score))
    return scored


def select_excerpts(
    question: str,
    context: str,
    *,
    top_k: int = 4,
    max_chars: int = 1200,
) -> List[Excerpt]:
    """Select up to ``top_k`` relevant excerpts within ``max_chars``."""
    sentences = split_sentences(context)
    if not sentences:
        return []

    ranked = sorted(rank_sentences(question, sentences), key=lambda item: (-item[1], item[0]))
    selected: List[Tuple[int, float, str]] = []
    used_chars = 0

    for position, score in ranked:
        if len(selected) >= top_k:
            break
        text = sentences[position]
        if used_chars and used_chars + len(text) > max_chars:
            continue
        if len(text) > max_chars:
            cut = text[:max_chars]
            text = cut.rsplit(" ", 1)[0] or cut
        selected.append((position, score, text))
        used_chars += len(text)

    if not selected:
        fallback_text = sentences[0][:max_chars]
        selected = [(0, 0.0, fallback_text)]

    return [
        Excerpt(index=index + 1, text=text, score=round(score, 4))
        for index, (_, score, text) in enumerate(selected)
    ]
