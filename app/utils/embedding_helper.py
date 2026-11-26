import json
import os
import logging
from mixedbread import Mixedbread

logger = logging.getLogger(__name__)


def parse_interests(value) -> list[str]:
    """Normalise interests from various storage formats (list, postgres array, json string, comma-separated string)."""
    if not value:
        return []
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if v is not None and str(v).strip()]
            except (ValueError, TypeError):
                pass
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1]
        return [part.strip().strip('"\'') for part in value.split(",") if part.strip().strip('"\'')]
    if isinstance(value, (list, tuple, set)):
        items = []
        for v in value:
            if v is not None:
                s = str(v).strip()
                if s:
                    items.append(s)
        return items
    return []


def parse_embedding(value) -> list[float] | None:
    """Normalise a vector/jsonb embedding from Supabase to a list of floats."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    try:
        parsed = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    return parsed or None


def cosine_similarity(a: list[float], b: list[float]) -> float | None:
    """Cosine similarity in [-1, 1], or None when the vectors cannot be compared."""
    if not a or not b or len(a) != len(b):
        return None
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return None
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


def generate_embedding(text: str) -> list[float] | None:
    try:
        mxbai = Mixedbread(api_key=os.environ.get("MXBAI_API_KEY"))
        response = mxbai.embed(
            model="mixedbread-ai/mxbai-embed-large-v1",
            input=[text],
            normalized=True,
            encoding_format="float",
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return None