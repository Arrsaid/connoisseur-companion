"""
Connoisseur Companion - host application powered by Claude.

Connects to the local MCP server (server.py) and runs a ReAct-style loop:
the LLM decides whether to call tools, calls them via the MCP server,
and continues until it produces a final text response.
"""

import os
from pathlib import Path

import gradio as gr
from anthropic import Anthropic
from dotenv import load_dotenv
from fastmcp.client import Client, PythonStdioTransport

# Load ANTHROPIC_API_KEY from the local .env file
load_dotenv()

# Configuration
SERVER_SCRIPT = str(Path(__file__).parent / "server.py")
MODEL_ID = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
MAX_AGENT_STEPS = 10  # safety cap on the ReAct loop

SYSTEM_PROMPT = """You are the Connoisseur Companion, a friendly assistant who \
helps people discover restaurants in California. You have access to a curated \
database via tools.

Available tools:
1. get_restaurant_info — look up a specific restaurant by name.
2. recommend_by_vibe — find restaurants matching a mood or atmosphere.
3. get_review — fetch a detailed review for a restaurant.

Guidelines:
- When the user asks about a specific restaurant, use get_restaurant_info first.
- When they describe a mood ("moody", "romantic", "zen"), use recommend_by_vibe.
- Keep responses warm, conversational, and concise.
- If the database has no answer, say so honestly.
"""

# Anthropic client
anthropic_client = Anthropic()


def mcp_tools_to_anthropic_format(mcp_tools) -> list[dict]:
    """Convert MCP tool definitions into Anthropic's tool schema format."""
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in mcp_tools
    ]


async def chat_with_agent(user_message: str, history: list) -> str:
    """Run one turn of the agent: connect to MCP, loop until Claude returns text."""
    transport = PythonStdioTransport(script_path=SERVER_SCRIPT)

    async with Client(transport) as client:
        # Discover the tools the MCP server exposes
        mcp_tools = await client.list_tools()
        tools = mcp_tools_to_anthropic_format(mcp_tools)

        # Build the conversation history
        messages = []
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        # ReAct loop - call tools until Claude returns a final text answer
        for _ in range(MAX_AGENT_STEPS):
            response = anthropic_client.messages.create(
                model=MODEL_ID,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )

            # If Claude is done thinking, return the final text answer
            if response.stop_reason == "end_turn":
                text_blocks = [b.text for b in response.content if b.type == "text"]
                return "\n".join(text_blocks).strip() or "(empty response)"

            # Otherwise Claude wants to use a tool - record its turn first
            messages.append({"role": "assistant", "content": response.content})

            # Execute every tool_use block via the MCP server
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = await client.call_tool(block.name, block.input)
                output = " ".join(
                    item.text if hasattr(item, "text") else str(item)
                    for item in result.content
                ) if result.content else "(no result)"
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        return "I couldn't complete that request after several attempts. Please try again."


# Gradio event handler
async def handle_chat(user_message, history):
    if history is None:
        history = []
    if not user_message or not user_message.strip():
        yield history
        return

    history = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": "Thinking..."},
    ]
    yield history

    response_text = await chat_with_agent(user_message, history[:-2])
    history[-1] = {"role": "assistant", "content": response_text}
    yield history


# Gradio interface
with gr.Blocks(title="Connoisseur Companion") as demo:
    gr.Markdown(
        "# Connoisseur Companion\n"
        "Your AI guide to California's restaurant scene. "
        "Ask me about restaurants by name, cuisine, or vibe!"
    )

    chatbot = gr.Chatbot(height=500, type="messages")
    msg_input = gr.Textbox(
        label="Ask about restaurants",
        placeholder='e.g., "Find me a moody spot in DTLA" or "Tell me about Sakura Garden"',
    )

    with gr.Row():
        btn1 = gr.Button("Find moody restaurants", size="sm")
        btn2 = gr.Button("Tell me about Iron & Embers", size="sm")
        btn3 = gr.Button("Zen dining in Little Tokyo?", size="sm")

    msg_input.submit(handle_chat, [msg_input, chatbot], [chatbot])
    msg_input.submit(lambda: "", None, msg_input)

    btn1.click(handle_chat, [gr.State("Find me some moody restaurants"), chatbot], [chatbot])
    btn2.click(handle_chat, [gr.State("Tell me about Iron & Embers"), chatbot], [chatbot])
    btn3.click(handle_chat, [gr.State("What's a zen dining experience in Little Tokyo?"), chatbot], [chatbot])


if __name__ == "__main__":
    print("Starting Connoisseur Companion...")
    demo.launch(share=False)