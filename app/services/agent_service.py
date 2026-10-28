"""
Service layer that wraps the Vertex AI Reasoning Engine SDK.

Centralises all interaction with the deployed AI agent so that
endpoint code never touches the SDK directly.
"""

import json
import logging
from collections import OrderedDict
from typing import Optional, List

import google.auth
from google.auth.transport.requests import Request
import requests

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_CACHED_SESSIONS = 10_000

class AgentService:
    def __init__(self):
        settings = get_settings()
        self._project_id = settings.project_id
        self._location = settings.location
        self._engine_id = settings.reasoning_engine_id

        # Get Google Cloud credentials
        self._credentials, _ = google.auth.default()
        self._api = f"https://{self._location}-aiplatform.googleapis.com/v1beta1/projects/{self._project_id}/locations/{self._location}/reasoningEngines/{self._engine_id}"
        self._endpoint = f"{self._api}:streamQuery"
        # Conversación del cliente -> sesión del agente. Es solo una caché: si la
        # instancia se reinicia, la sesión se vuelve a buscar en Vertex.
        self._sessions: OrderedDict[str, str] = OrderedDict()

    def init(self):
        """No complex initialization needed for REST client."""
        logger.info(f"Initialized AgentService pointing to Reasoning Engine: {self._engine_id} at {self._location}")

    def query_agent(self, prompt: str, session_id: Optional[str] = None) -> str:
        """Sends a query to the Vertex AI Reasoning Engine.

        session_id identifica la conversación del cliente: se usa como user_id del
        agente y para reutilizar su sesión, de modo que el agente recuerde los
        mensajes anteriores. Si no se puede obtener la sesión, responde sin memoria.
        """
        try:
            # Refresh credentials if needed
            if not self._credentials.valid:
                self._credentials.refresh(Request())
        except Exception as e:
            logger.error(f"Error refreshing credentials: {str(e)}")
            raise RuntimeError(f"Error consultando al agente: {str(e)}")

        headers = {
            "Authorization": f"Bearer {self._credentials.token}",
            "Content-Type": "application/json"
        }
        user_id = session_id or "default-user"
        agent_session = self._agent_session(session_id, headers) if session_id else None

        try:
            reply = self._send(prompt, user_id, agent_session, headers)
        except RuntimeError:
            if not agent_session:
                raise
            reply = ""
        if not reply and agent_session:
            # Con una sesión vencida o borrada el agente responde vacío (HTTP 200): se
            # reintenta una vez sin ella y el agente abre una nueva para la conversación.
            logger.warning(f"Sin respuesta con la sesión {agent_session} de {session_id}; se reintenta sin ella")
            self._sessions.pop(session_id, None)
            reply = self._send(prompt, user_id, None, headers)
        return reply or "El agente no devolvió ninguna respuesta (vacío)."

    def _agent_session(self, conversation_id: str, headers: dict) -> Optional[str]:
        """Devuelve la sesión del agente para una conversación, o None si aún no tiene.

        Cuando el agente recibe un mensaje sin session_id crea una sesión en Vertex
        (vence a los 7 días) con user_id igual al id de la conversación. Por eso basta
        con buscarla: el primer mensaje va sin sesión y los siguientes la reutilizan.
        Si Vertex falla, devuelve None y el mensaje se responde sin memoria.
        """
        if conversation_id in self._sessions:
            self._sessions.move_to_end(conversation_id)
            return self._sessions[conversation_id]

        literal = conversation_id.replace("\\", "\\\\").replace('"', '\\"')
        try:
            response = requests.get(
                f"{self._api}/sessions",
                headers=headers,
                params={"filter": f'user_id="{literal}"', "pageSize": 100},
                timeout=15,
            )
            response.raise_for_status()
            sessions = response.json().get("sessions", [])
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.warning(f"No se pudo buscar la sesión de {conversation_id}, se responde sin memoria: {e}")
            return None
        if not sessions:
            return None

        latest = max(sessions, key=lambda s: s.get("updateTime", ""))
        agent_session = latest["name"].rsplit("/", 1)[-1]
        self._sessions[conversation_id] = agent_session
        if len(self._sessions) > MAX_CACHED_SESSIONS:
            self._sessions.popitem(last=False)
        return agent_session

    def _send(self, prompt: str, user_id: str, agent_session: Optional[str], headers: dict) -> str:
        try:
            payload = {
                "classMethod": "stream_query",
                "input": {
                    "message": prompt,
                    "user_id": user_id
                }
            }
            if agent_session:
                payload["input"]["session_id"] = agent_session

            logger.info(f"Sending request to Reasoning Engine for user {user_id}, session {agent_session}")
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
