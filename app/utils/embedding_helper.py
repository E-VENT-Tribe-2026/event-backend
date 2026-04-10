import os
from mixedbread import Mixedbread

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
        print(f"Embedding generation failed: {e}")
        return None