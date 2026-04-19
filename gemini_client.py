from google import genai
from google.genai import types

# Дефолтная системная инструкция: просим стандартный Markdown, который
# telegramify-markdown сможет чисто конвертировать в Telegram MarkdownV2.
# Telegram MarkdownV2 напрямую не просим — Gemini на нём обучен плохо,
# и экранирование всё равно делает telegramify-markdown.
DEFAULT_SYSTEM_INSTRUCTION = (
    "You are a helpful assistant replying inside a Telegram chat. "
    "Answer in the same language the user writes in. "
    "Format every reply using standard Markdown only, keeping it simple "
    "so it renders cleanly in Telegram:\n"
    "- **bold**, *italic*, `inline code`\n"
    "- fenced code blocks with a language tag, e.g. ```python ... ```\n"
    "- bulleted lists with `-` and numbered lists with `1.`\n"
    "- [text](https://url) for links\n"
    "- `#`, `##`, `###` for headings\n"
    "Do NOT use HTML, tables, footnotes, task lists, strikethrough, "
    "blockquotes that rely on leading `>` on every line, or experimental "
    "Markdown extensions. Do NOT wrap the whole answer in a single code "
    "block unless the user explicitly asks for code."
)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        system_instruction: str | None = None,
    ):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._system_instruction = system_instruction or None

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
        config = None
        if self._system_instruction:
            config = types.GenerateContentConfig(
                system_instruction=self._system_instruction,
            )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )
        return response.text or ""
