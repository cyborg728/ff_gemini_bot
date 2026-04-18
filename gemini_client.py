from google import genai
from google.genai import types


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    @staticmethod
    def _build_contents(
        history: list[tuple[str, str]],
        user_message: str,
    ) -> list[types.Content]:
        contents = [
            types.Content(role=role, parts=[types.Part.from_text(text=text)])
            for role, text in history
        ]
        contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
        )
        return contents

    async def generate(
        self,
        history: list[tuple[str, str]],
        user_message: str,
    ) -> str:
        contents = self._build_contents(history, user_message)
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
        )
        return response.text or ""
