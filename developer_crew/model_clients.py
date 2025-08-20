"""Multi-provider model client abstraction for Developer Crew."""

import os
from typing import Optional, Dict, Any, Union
from abc import ABC, abstractmethod

# Import model clients based on availability
try:
    from autogen_ext.models.openai import OpenAIChatCompletionClient
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from autogen_ext.models.anthropic import AnthropicChatCompletionClient
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from autogen_ext.models.gemini import GeminiChatCompletionClient
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


class ModelClientFactory:
    """Factory for creating model clients from different providers."""
    
    SUPPORTED_PROVIDERS = {
        "openai": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
        "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
        "google": ["gemini-pro", "gemini-pro-vision", "gemini-1.5-pro"]
    }
    
    @staticmethod
    def create_client(model: str, api_key: Optional[str] = None):
        """Create a model client based on the model name.
        
        Args:
            model: Model name (e.g., 'claude-3-5-sonnet-20241022', 'gpt-4', 'gemini-pro')
            api_key: API key for the provider (optional, will use env vars)
        
        Returns:
            Model client instance
        
        Raises:
            ValueError: If model/provider is not supported
            ImportError: If required client library is not installed
        """
        provider = ModelClientFactory._get_provider_from_model(model)
        
        if provider == "openai":
            return ModelClientFactory._create_openai_client(model, api_key)
        elif provider == "anthropic":
            return ModelClientFactory._create_anthropic_client(model, api_key)
        elif provider == "google":
            return ModelClientFactory._create_google_client(model, api_key)
        else:
            raise ValueError(f"Unsupported model: {model}")
    
    @staticmethod
    def _get_provider_from_model(model: str) -> str:
        """Determine provider from model name."""
        for provider, models in ModelClientFactory.SUPPORTED_PROVIDERS.items():
            if any(model.startswith(m.split('-')[0]) for m in models) or model in models:
                return provider
        
        # Fallback logic for common patterns
        if "gpt" in model.lower() or "openai" in model.lower():
            return "openai"
        elif "claude" in model.lower() or "anthropic" in model.lower():
            return "anthropic"
        elif "gemini" in model.lower() or "google" in model.lower():
            return "google"
        
        raise ValueError(f"Cannot determine provider for model: {model}")
    
    @staticmethod
    def _create_openai_client(model: str, api_key: Optional[str] = None):
        """Create OpenAI client."""
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI client not available. Install with: pip install autogen-ext[openai]")
        
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key not provided and OPENAI_API_KEY not set")
        
        return OpenAIChatCompletionClient(
            model=model,
            api_key=api_key
        )
    
    @staticmethod
    def _create_anthropic_client(model: str, api_key: Optional[str] = None):
        """Create Anthropic client."""
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic client not available. Install with: pip install autogen-ext[anthropic]")
        
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Anthropic API key not provided and ANTHROPIC_API_KEY not set")
        
        return AnthropicChatCompletionClient(
            model=model,
            api_key=api_key
        )
    
    @staticmethod
    def _create_google_client(model: str, api_key: Optional[str] = None):
        """Create Google client."""
        if not GEMINI_AVAILABLE:
            raise ImportError("Gemini client not available. Install with: pip install autogen-ext[gemini]")
        
        api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Google API key not provided and GOOGLE_API_KEY/GEMINI_API_KEY not set")
        
        return GeminiChatCompletionClient(
            model=model,
            api_key=api_key
        )
    
    @staticmethod
    def get_available_models() -> Dict[str, list]:
        """Get available models based on installed clients and API keys."""
        available = {}
        
        if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            available["openai"] = ModelClientFactory.SUPPORTED_PROVIDERS["openai"]
        
        if ANTHROPIC_AVAILABLE and os.getenv("ANTHROPIC_API_KEY"):
            available["anthropic"] = ModelClientFactory.SUPPORTED_PROVIDERS["anthropic"]
        
        if GEMINI_AVAILABLE and (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
            available["google"] = ModelClientFactory.SUPPORTED_PROVIDERS["google"]
        
        return available
    
    @staticmethod
    def validate_setup() -> Dict[str, Any]:
        """Validate the current setup and return status information."""
        status = {
            "providers": {},
            "available_models": [],
            "missing_dependencies": [],
            "missing_api_keys": []
        }
        
        # Check OpenAI
        if OPENAI_AVAILABLE:
            has_key = bool(os.getenv("OPENAI_API_KEY"))
            status["providers"]["openai"] = {"installed": True, "has_api_key": has_key}
            if has_key:
                status["available_models"].extend([f"openai:{m}" for m in ModelClientFactory.SUPPORTED_PROVIDERS["openai"]])
            else:
                status["missing_api_keys"].append("OPENAI_API_KEY")
        else:
            status["providers"]["openai"] = {"installed": False, "has_api_key": False}
            status["missing_dependencies"].append("autogen-ext[openai]")
        
        # Check Anthropic
        if ANTHROPIC_AVAILABLE:
            has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
            status["providers"]["anthropic"] = {"installed": True, "has_api_key": has_key}
            if has_key:
                status["available_models"].extend([f"anthropic:{m}" for m in ModelClientFactory.SUPPORTED_PROVIDERS["anthropic"]])
            else:
                status["missing_api_keys"].append("ANTHROPIC_API_KEY")
        else:
            status["providers"]["anthropic"] = {"installed": False, "has_api_key": False}
            status["missing_dependencies"].append("autogen-ext[anthropic]")
        
        # Check Google
        if GEMINI_AVAILABLE:
            has_key = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
            status["providers"]["google"] = {"installed": True, "has_api_key": has_key}
            if has_key:
                status["available_models"].extend([f"google:{m}" for m in ModelClientFactory.SUPPORTED_PROVIDERS["google"]])
            else:
                status["missing_api_keys"].append("GOOGLE_API_KEY or GEMINI_API_KEY")
        else:
            status["providers"]["google"] = {"installed": False, "has_api_key": False}
            status["missing_dependencies"].append("autogen-ext[gemini]")
        
        return status


def get_default_model() -> Optional[str]:
    """Get the default model based on available API keys."""
    available = ModelClientFactory.get_available_models()
    
    # Priority: Claude > GPT-4 > Gemini
    if "anthropic" in available:
        return "claude-3-5-sonnet-20241022"
    elif "openai" in available:
        return "gpt-4"
    elif "google" in available:
        return "gemini-pro"
    
    return None