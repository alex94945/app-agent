# common/llm.py

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from common.config import settings

def get_llm_client(purpose: str = "planner") -> BaseChatModel:
    """
    Factory function to get the LLM client.
    
    For now, it returns a configured OpenAI client. In the future, this
    can be expanded to return different models based on the 'purpose'.

    Args:
        purpose: A string indicating the intended use of the LLM (e.g., 'planner', 'router').

    Returns:
        An instance of a LangChain chat model client.
    """
    # For now, we only have one configuration, but this structure allows for future expansion.
    if purpose == "planner":
        # The ChatOpenAI class will use the OPENAI_API_KEY from the environment
        # if the api_key argument is not provided. We pass it from our settings
        # for clarity and to ensure it respects the .env file.
        return ChatOpenAI(
            api_key=settings.OPENAI_API_KEY, 
            model=settings.OPENAI_MODEL_NAME
        )
    
    # Default fallback
    return ChatOpenAI(
        api_key=settings.OPENAI_API_KEY, 
        model=settings.OPENAI_MODEL_NAME
    )
