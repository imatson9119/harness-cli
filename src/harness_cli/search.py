from __future__ import annotations

import difflib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

SEARCH_INDEX_SCHEMA_VERSION = 2
MAX_TERMS_PER_DOCUMENT = 120
MIN_RELATIVE_RESULT_SCORE = 0.30
MIN_ABSOLUTE_RESULT_SCORE = 0.03

TOKEN_RE = re.compile(r"[a-z0-9]+")
CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")

STOP_WORDS = {
    "a",
    "all",
    "an",
    "and",
    "api",
    "as",
    "at",
    "based",
    "be",
    "by",
    "for",
    "from",
    "given",
    "in",
    "is",
    "of",
    "on",
    "or",
    "requested",
    "specified",
    "the",
    "this",
    "to",
    "used",
    "using",
    "with",
}

FIELD_WEIGHTS = {
    "command": 5.5,
    "operation_id": 4.5,
    "group": 4.0,
    "tag": 3.5,
    "summary": 3.0,
    "path": 1.8,
    "parameter_names": 1.8,
    "method": 1.0,
    "description": 0.9,
    "parameter_descriptions": 0.45,
}


@dataclass(frozen=True)
class SearchIndex:
    source_hash: str
    operation_count: int
    vocabulary: tuple[str, ...]
    idf: tuple[float, ...]
    vectors: dict[str, tuple[tuple[int, float], ...]]


def rank_operations(
    query: str,
    operations: Sequence[Any],
    *,
    source_hash: str,
) -> list[Any]:
    index = _load_search_index(source_hash, len(operations)) or _build_search_index(
        operations,
        source_hash=source_hash,
    )
    query_tokens = _tokens(query)
    query_vector = _normalized_vector(_query_terms(query, query_tokens, index), index)
    scored: list[tuple[float, str, str, Any]] = []

    for operation in operations:
        operation_id = _string_value(operation, "operation_id")
        score = _dot(query_vector, index.vectors.get(operation_id, ()))
        score += _exact_match_bonus(query_tokens, operation)
        if score > 0:
            scored.append(
                (
                    score,
                    _string_value(operation, "group"),
                    _string_value(operation, "command"),
                    operation,
                )
            )

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    if scored:
        minimum_score = max(MIN_ABSOLUTE_RESULT_SCORE, scored[0][0] * MIN_RELATIVE_RESULT_SCORE)
        scored = [item for item in scored if item[0] >= minimum_score]
    return [operation for _, _, _, operation in scored]


def build_search_index_data(operations: Sequence[Any], source_hash: str) -> dict[str, Any]:
    index = _build_search_index(operations, source_hash=source_hash)
    return {
        "schema_version": SEARCH_INDEX_SCHEMA_VERSION,
        "source_hash": index.source_hash,
        "operation_count": index.operation_count,
        "vocabulary": list(index.vocabulary),
        "idf": [round(value, 6) for value in index.idf],
        "operations": [
            {
                "operation_id": operation_id,
                "vector": [[term_id, round(weight, 6)] for term_id, weight in vector],
            }
            for operation_id, vector in index.vectors.items()
        ],
    }


def validate_search_index_data(manifest: Mapping[str, Any], index: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    operations = manifest.get("operations")
    if not isinstance(operations, list):
        return ["search index validation requires manifest operations"]
    if index.get("schema_version") != SEARCH_INDEX_SCHEMA_VERSION:
        errors.append(f"search index schema_version must be {SEARCH_INDEX_SCHEMA_VERSION}")
    if index.get("source_hash") != manifest.get("source_hash"):
        errors.append("search index source_hash does not match manifest source_hash")
    if index.get("operation_count") != len(operations):
        errors.append("search index operation_count does not match manifest operations length")

    vocabulary = index.get("vocabulary")
    idf = index.get("idf")
    index_operations = index.get("operations")
    if not isinstance(vocabulary, list) or not all(isinstance(item, str) for item in vocabulary):
        errors.append("search index vocabulary must be a list of strings")
        vocabulary = []
    if not isinstance(idf, list) or len(idf) != len(vocabulary):
        errors.append("search index idf must match vocabulary length")
    elif not all(isinstance(item, int | float) for item in idf):
        errors.append("search index idf values must be numbers")
    if not isinstance(index_operations, list):
        errors.append("search index operations must be a list")
        return errors

    manifest_ids = [_mapping_string_value(operation, "operation_id") for operation in operations]
    index_ids: list[str] = []
    for position, item in enumerate(index_operations):
        if not isinstance(item, dict):
            errors.append(f"search index operation {position} must be an object")
            continue
        operation_id = item.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            errors.append(f"search index operation {position} missing operation_id")
            continue
        index_ids.append(operation_id)
        vector = item.get("vector")
        if not isinstance(vector, list):
            errors.append(f"search index operation {operation_id}: vector must be a list")
            continue
        for term in vector:
            if not _valid_vector_entry(term, len(vocabulary)):
                errors.append(f"search index operation {operation_id}: invalid vector entry")
                break
    if manifest_ids != index_ids:
        errors.append("search index operation ids must match manifest operation order")
    return errors


def _valid_vector_entry(value: Any, vocabulary_size: int) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    term_id, weight = value
    return (
        isinstance(term_id, int)
        and 0 <= term_id < vocabulary_size
        and isinstance(weight, int | float)
    )


@lru_cache(maxsize=4)
def _load_search_index(source_hash: str, operation_count: int) -> SearchIndex | None:
    try:
        with (
            resources.files("harness_cli.data")
            .joinpath("search_index.json")
            .open("r", encoding="utf-8") as handle
        ):
            data = json.load(handle)
    except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != SEARCH_INDEX_SCHEMA_VERSION:
        return None
    if data.get("source_hash") != source_hash or data.get("operation_count") != operation_count:
        return None

    vocabulary = data.get("vocabulary")
    idf = data.get("idf")
    raw_operations = data.get("operations")
    if not isinstance(vocabulary, list) or not isinstance(idf, list):
        return None
    if not isinstance(raw_operations, list) or len(vocabulary) != len(idf):
        return None

    vectors: dict[str, tuple[tuple[int, float], ...]] = {}
    for item in raw_operations:
        if not isinstance(item, dict):
            return None
        operation_id = item.get("operation_id")
        vector = item.get("vector")
        if not isinstance(operation_id, str) or not isinstance(vector, list):
            return None
        entries: list[tuple[int, float]] = []
        for entry in vector:
            if not _valid_vector_entry(entry, len(vocabulary)):
                return None
            entries.append((int(entry[0]), float(entry[1])))
        vectors[operation_id] = tuple(entries)
    return SearchIndex(
        source_hash=source_hash,
        operation_count=operation_count,
        vocabulary=tuple(str(item) for item in vocabulary),
        idf=tuple(float(item) for item in idf),
        vectors=vectors,
    )


def _build_search_index(operations: Sequence[Any], *, source_hash: str) -> SearchIndex:
    documents = [_operation_terms(operation) for operation in operations]
    document_frequency: Counter[str] = Counter()
    for terms in documents:
        document_frequency.update(terms.keys())

    vocabulary = tuple(sorted(document_frequency))
    term_ids = {term: index for index, term in enumerate(vocabulary)}
    operation_count = len(operations)
    idf = tuple(
        math.log((1 + operation_count) / (1 + document_frequency[term])) + 1.0
        for term in vocabulary
    )

    vectors: dict[str, tuple[tuple[int, float], ...]] = {}
    for operation, terms in zip(operations, documents, strict=True):
        weighted = {
            term_ids[term]: weight * idf[term_ids[term]]
            for term, weight in terms.items()
            if term in term_ids
        }
        top_terms = sorted(weighted.items(), key=lambda item: (-item[1], item[0]))[
            :MAX_TERMS_PER_DOCUMENT
        ]
        norm = math.sqrt(sum(weight * weight for _, weight in top_terms)) or 1.0
        vectors[_string_value(operation, "operation_id")] = tuple(
            (term_id, weight / norm) for term_id, weight in top_terms
        )

    return SearchIndex(
        source_hash=source_hash,
        operation_count=operation_count,
        vocabulary=vocabulary,
        idf=idf,
        vectors=vectors,
    )


def _operation_terms(operation: Any) -> dict[str, float]:
    terms: dict[str, float] = {}
    _add_text_features(terms, _string_value(operation, "command"), FIELD_WEIGHTS["command"])
    _add_text_features(
        terms,
        _string_value(operation, "operation_id"),
        FIELD_WEIGHTS["operation_id"],
    )
    _add_text_features(terms, _string_value(operation, "group"), FIELD_WEIGHTS["group"])
    _add_text_features(terms, _string_value(operation, "tag"), FIELD_WEIGHTS["tag"])
    _add_text_features(terms, _string_value(operation, "summary"), FIELD_WEIGHTS["summary"])
    _add_text_features(terms, _string_value(operation, "path"), FIELD_WEIGHTS["path"])
    _add_text_features(terms, _string_value(operation, "method"), FIELD_WEIGHTS["method"])
    _add_text_features(
        terms,
        _string_value(operation, "description"),
        FIELD_WEIGHTS["description"],
    )

    parameter_names: list[str] = []
    parameter_descriptions: list[str] = []
    for parameter in _parameters(operation):
        parameter_names.append(_string_value(parameter, "name"))
        parameter_descriptions.append(_string_value(parameter, "description"))
    _add_text_features(terms, " ".join(parameter_names), FIELD_WEIGHTS["parameter_names"])
    _add_text_features(
        terms,
        " ".join(parameter_descriptions),
        FIELD_WEIGHTS["parameter_descriptions"],
    )
    return terms


def _query_terms(query: str, tokens: Sequence[str], index: SearchIndex) -> dict[str, float]:
    terms: dict[str, float] = {}
    _add_text_features(terms, query, 1.0)
    vocabulary = set(index.vocabulary)
    token_vocabulary = _token_vocabulary(index)
    for token in tokens:
        if f"tok:{token}" in vocabulary:
            continue
        match = _closest_token(token, token_vocabulary)
        if match:
            _add_token_features(terms, [match], 0.85)
    return terms


def _token_vocabulary(index: SearchIndex) -> tuple[str, ...]:
    return tuple(term.removeprefix("tok:") for term in index.vocabulary if term.startswith("tok:"))


def _closest_token(token: str, vocabulary: Sequence[str]) -> str | None:
    matches = difflib.get_close_matches(token, vocabulary, n=1, cutoff=0.78)
    return matches[0] if matches else None


def _normalized_vector(
    terms: Mapping[str, float], index: SearchIndex
) -> tuple[tuple[int, float], ...]:
    term_ids = {term: position for position, term in enumerate(index.vocabulary)}
    weighted = []
    for term, weight in terms.items():
        term_id = term_ids.get(term)
        if term_id is not None:
            weighted.append((term_id, weight * index.idf[term_id]))
    norm = math.sqrt(sum(weight * weight for _, weight in weighted)) or 1.0
    return tuple((term_id, weight / norm) for term_id, weight in weighted)


def _dot(left: Iterable[tuple[int, float]], right: Iterable[tuple[int, float]]) -> float:
    left_dict = dict(left)
    return sum(weight * left_dict.get(term_id, 0.0) for term_id, weight in right)


def _exact_match_bonus(query_tokens: Sequence[str], operation: Any) -> float:
    if not query_tokens:
        return 0.0
    query_slug = "-".join(query_tokens)
    command = _string_value(operation, "command").lower()
    operation_id = _string_value(operation, "operation_id").lower()
    group = _string_value(operation, "group").lower()
    tag_slug = "-".join(_tokens(_string_value(operation, "tag")))

    if query_slug in {command, operation_id}:
        return 0.15
    if query_slug in {group, tag_slug}:
        return 0.10
    if command.startswith(query_slug) or operation_id.startswith(query_slug):
        return 0.08
    if query_slug and (query_slug in command or query_slug in operation_id):
        return 0.05
    if query_slug and (query_slug in group or query_slug in tag_slug):
        return 0.03
    return 0.0


def _add_text_features(terms: dict[str, float], text: str, weight: float) -> None:
    _add_token_features(terms, _tokens(text), weight)
    for token in _literal_tokens(text):
        _add_term(terms, f"lit:{token}", weight * 0.8)


def _add_token_features(terms: dict[str, float], tokens: Sequence[str], weight: float) -> None:
    for token in tokens:
        _add_term(terms, f"tok:{token}", weight)
        for gram in _character_ngrams(token):
            _add_term(terms, f"chr:{gram}", weight * 0.28)
    for first, second in zip(tokens, tokens[1:], strict=False):
        _add_term(terms, f"big:{first}_{second}", weight * 1.15)


def _add_term(terms: dict[str, float], term: str, weight: float) -> None:
    terms[term] = terms.get(term, 0.0) + weight


def _character_ngrams(token: str) -> Iterable[str]:
    if len(token) < 4:
        return ()
    padded = f"<{token}>"
    return (
        padded[index : index + size] for size in (2, 3) for index in range(len(padded) - size + 1)
    )


def _tokens(value: str) -> list[str]:
    return [_normalize_token(token) for token in _literal_tokens(value)]


def _literal_tokens(value: str) -> list[str]:
    text = ACRONYM_BOUNDARY_RE.sub(r"\1 \2", value)
    text = CAMEL_BOUNDARY_RE.sub(r"\1 \2", text)
    tokens = [match.group(0) for match in TOKEN_RE.finditer(text.lower())]
    return [token for token in tokens if len(token) > 1 and token not in STOP_WORDS]


def _normalize_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _parameters(operation: Any) -> Sequence[Any]:
    if isinstance(operation, Mapping):
        parameters = operation.get("parameters", ())
        return parameters if isinstance(parameters, Sequence) else ()
    parameters = getattr(operation, "parameters", ())
    return parameters if isinstance(parameters, Sequence) else ()


def _string_value(item: Any, field: str) -> str:
    if isinstance(item, Mapping):
        return _mapping_string_value(item, field)
    value = getattr(item, field, "")
    return value if isinstance(value, str) else ""


def _mapping_string_value(item: Mapping[str, Any], field: str) -> str:
    value = item.get(field)
    return value if isinstance(value, str) else ""
