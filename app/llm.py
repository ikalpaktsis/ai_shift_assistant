import os
from openai import OpenAI


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key=None, model=None, temperature=0.2, timeout=60):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise LLMError("OPENAI_API_KEY is required to run the agent.")
        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE", temperature))

    def chat(self, messages, tools=None, tool_choice="auto"):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=self.temperature,
        )
        msg = resp.choices[0].message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                )
        return {"content": msg.content, "tool_calls": tool_calls}

    def generate_text(self, system_prompt, user_prompt):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
        )
        return resp.choices[0].message.content or ""
