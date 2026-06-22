"""
Service layer that wraps the Vertex AI Reasoning Engine SDK.

Centralises all interaction with the deployed AI agent so that
endpoint code never touches the SDK directly.
"""

import json
import logging
from typing import Optional, List

import google.auth
from google.auth.transport.requests import Request
import requests

from app.core.config import get_settings

logger = logging.getLogger(__name__)

class AgentService:
    def __init__(self):
        settings = get_settings()
        self._project_id = settings.project_id
        self._location = settings.location
        self._engine_id = settings.reasoning_engine_id
        
        # Get Google Cloud credentials
        self._credentials, _ = google.auth.default()
        self._endpoint = f"https://{self._location}-aiplatform.googleapis.com/v1beta1/projects/{self._project_id}/locations/{self._location}/reasoningEngines/{self._engine_id}:streamQuery"

    def init(self):
        """No complex initialization needed for REST client."""
        logger.info(f"Initialized AgentService pointing to Reasoning Engine: {self._engine_id} at {self._location}")

    def query_agent(self, prompt: str, session_id: Optional[str] = None) -> str:
        """Sends a query to the Vertex AI Reasoning Engine."""
        try:
            # Refresh credentials if needed
            if not self._credentials.valid:
                self._credentials.refresh(Request())

            headers = {
                "Authorization": f"Bearer {self._credentials.token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "classMethod": "stream_query",
                "input": {
                    "message": prompt,
                    "user_id": session_id or "default-user"
                }
            }

            logger.info(f"Sending request to Reasoning Engine for session {session_id}")
            response = requests.post(self._endpoint, headers=headers, json=payload, timeout=60)
            
            # Raise an exception for bad status codes
            response.raise_for_status()

            # The response is a stream of JSON chunks
            lines = response.text.strip().splitlines()
            full_response = ""
            for line in lines:
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        if "error_message" in data:
                            raise RuntimeError(f"Agent error: {data['error_message']}")
                        if "output" in data:
                            full_response += str(data["output"])
                        elif "text" in data:
                            full_response += data["text"]
                        elif "content" in data and "parts" in data["content"] and len(data["content"]["parts"]) > 0:
                            part = data["content"]["parts"][0]
                            if "text" in part:
                                full_response += part["text"]
                    else:
                        full_response += str(data)
                except json.JSONDecodeError:
                    full_response += line
                    
            if not full_response:
                return "El agente no devolvió ninguna respuesta (vacío)."
                
            return full_response

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP Error querying agent: {str(e)}")
            if e.response is not None:
                logger.error(f"Response content: {e.response.text}")
            raise RuntimeError(f"Error de conexión con el Agente: {str(e)}")
        except Exception as e:
            logger.error(f"Error consulting agent: {str(e)}")
            raise RuntimeError(f"Error consultando al agente: {str(e)}")

# Module-level instance for backward compatibility
_agent_service = AgentService()

def init() -> None:
    _agent_service.init()

def query_agent(message: str, session_id: str) -> str:
    """Module-level wrapper for query_agent."""
    return _agent_service.query_agent(message, session_id)
