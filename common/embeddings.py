# common/embeddings.py

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from common.config import settings

def get_embedding_model() -> Embeddings:
    """
    Factory function to get the embedding model client based on the
    provider specified in the application settings.

    Raises:
        ValueError: If the configured EMBED_PROVIDER is not supported.

    Returns:
        An instance of a LangChain embedding model client.
    """
    provider = settings.EMBED_PROVIDER.lower()
    
    if provider == "openai":
        # The OpenAIEmbeddings class will automatically use the OPENAI_API_KEY
        # from the environment if not passed explicitly. We pass it for clarity.
        return OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)
    
    # Add elif blocks here for other providers in the future
    # elif provider == "google":
    #     from langchain_google_genai import GoogleGenerativeAIEmbeddings
    #     return GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=settings.GOOGLE_API_KEY)
    
    else:
        raise ValueError(f"Unsupported embedding provider configured: '{settings.EMBED_PROVIDER}'")

# Example of how to use this in other files:
# from common.embeddings import get_embedding_model
# embeddings = get_embedding_model()