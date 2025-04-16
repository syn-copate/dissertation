from os import getenv
from openai import OpenAI

api_key = getenv("agicto_api_key")
if not api_key:
    raise KeyError("agicto_api_key not found in environment variable")
client = OpenAI(api_key=api_key, base_url="https://api.agicto.cn/v1")


def request_llm(messages: list[dict], model: str = "ERNIE-Speed-8K", timeout: int = 30):
    """
    Send request via agicto, please set agicto_api_key environment:

    `setx agicto_api_key <API_KEY>`, or

    `export agicto_api_key="<API_KEY>"`

    See https://agicto.com/model for supported models.
    """
    chat_completion = client.chat.completions.create(
        messages=messages, model=model, timeout=timeout
    )
    if chat_completion and chat_completion.choices:
        return chat_completion.choices[0].message.content
    raise Exception(
        chat_completion.error if hasattr(chat_completion, "error") else chat_completion
    )


def test():
    messages = [
        {
            "role": "user",
            "content": "translate to chinese:\nNow we have the basic parts out of the way, we can get to writing a linter! Instead of Python, we’ll continue working with Imp. Note that it’s easy to adapt this linter for any language with a tree-sitter grammar. Imp also has a much simpler semantics than Python so we can just focus on “obviously correct” lints rather than worry about suggestions changing program behavior.",
        }
    ]
    print(request_llm(messages, "gemma2-9b-it"))


if __name__ == "__main__":
    test()
