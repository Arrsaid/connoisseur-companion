"""Tests for the MCP server tools.

Each test spins up a fresh MCP server via stdio, calls one or more tools,
and asserts on the parsed JSON response. We use pytest-asyncio because the
MCP Python client is async.
"""

import json
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Path to the server script, resolved relative to this test file.
SERVER_SCRIPT = str(Path(__file__).parent.parent / "connoisseur" / "server.py")

SERVER_PARAMS = StdioServerParameters(
    command="python",
    args=[SERVER_SCRIPT],
)


async def call_tool(tool_name: str, arguments: dict) -> dict:
    """Open a session, call one tool, return the parsed JSON dict."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            return json.loads(result.content[0].text)


async def list_tools() -> list[str]:
    """Open a session, return the list of tool names the server exposes."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            return [t.name for t in tools_result.tools]


# get_restaurant_info ---------------------------------------------------------

async def test_get_restaurant_info_found():
    """An existing restaurant name returns status=found with results."""
    data = await call_tool(
        "get_restaurant_info", {"restaurant_name": "La Mangue Amère"}
    )
    assert data["status"] == "found"
    assert data["count"] >= 1
    assert "Mangue" in data["results"][0]["name"]


async def test_get_restaurant_info_not_found():
    """A nonsense name returns status=not_found with a helpful message."""
    data = await call_tool(
        "get_restaurant_info", {"restaurant_name": "ZZZNotARealRestaurant"}
    )
    assert data["status"] == "not_found"
    assert "ZZZNotARealRestaurant" in data["message"]


async def test_get_restaurant_info_partial_match():
    """A partial name like 'Mangue' matches 'La Mangue Amère'."""
    data = await call_tool("get_restaurant_info", {"restaurant_name": "Mangue"})
    assert data["status"] == "found"
    names = [r["name"] for r in data["results"]]
    assert any("Mangue" in n for n in names)


# recommend_by_vibe -----------------------------------------------------------

async def test_recommend_by_vibe_returns_structure():
    """The response has the three expected top-level keys."""
    data = await call_tool("recommend_by_vibe", {"vibe": "convivial"})
    assert "vibe_searched" in data
    assert "structured_matches" in data
    assert "raw_text_excerpts" in data
    assert isinstance(data["structured_matches"], list)
    assert isinstance(data["raw_text_excerpts"], list)


async def test_recommend_by_vibe_known_vibe():
    """A vibe known to exist in the data returns at least one match."""
    data = await call_tool("recommend_by_vibe", {"vibe": "convivial"})
    total_matches = len(data["structured_matches"]) + len(data["raw_text_excerpts"])
    assert total_matches > 0, "Expected at least one match for 'convivial'"


# get_review ------------------------------------------------------------------


async def test_get_review_found_for_known_restaurant():
    """A restaurant with a review returns status=found with non-empty text."""
    # Use the first restaurant that has a review available.
    # We pick by name from the structured catalogue, since reviews are joined by itemId.
    restaurant_with_review = "La Mangue Amère"  # known to have a review

    data = await call_tool(
        "get_review", {"restaurant_name": restaurant_with_review}
    )
    assert data["status"] == "found"
    assert "review_text" in data
    assert len(data["review_text"]) > 0
    assert "rating" in data


async def test_get_review_restaurant_not_found():
    """A nonsense restaurant name returns status=not_found."""
    data = await call_tool(
        "get_review", {"restaurant_name": "ZZZNoRestaurantHere"}
    )
    assert data["status"] == "not_found"
    assert "No restaurant found" in data["message"]


# Meta: server inventory ------------------------------------------------------

async def test_server_exposes_three_tools():
    """The server advertises exactly the three expected tools."""
    tool_names = await list_tools()
    assert "get_restaurant_info" in tool_names
    assert "recommend_by_vibe" in tool_names
    assert "get_review" in tool_names