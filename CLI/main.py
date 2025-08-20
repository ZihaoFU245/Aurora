"""
This is the application entry point for the cli version aurora agent application
Show only import and run
"""
from typing import List
from langchain_core.messages import AIMessage, AnyMessage

from core.engine import Engine
from CurrentTimeTools.Tools import getCurrentTime


def _last_ai_text(messages: List[AnyMessage]) -> str:
    for m in reversed(messages or []):
        if isinstance(m, AIMessage):
            return str(m.content)
    return ""


def main():
    print("Start")

    # Initialize engine with tools
    tools = [getCurrentTime]
    engine = Engine(tools=tools)

    history: List[AnyMessage] = []

    while True:
        try:
            q = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            break
        if q in ("/exit", "/quit"):
            print("bye.")
            break
        if not q:
            continue

        # Run the agent once and update history
        result = engine.run(q, history=history)
        history = result.get("messages", history)
        print(f"Assistant> {_last_ai_text(history)}")


if __name__ == "__main__":
    main()

