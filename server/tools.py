import json
import time

TOOLS = [
    {
        "type": "function",
        "name": "add_task",
        "description": "Record an action item the moment someone commits to doing something.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What needs to happen, starting with a verb."},
                "owner": {"type": "string", "description": "Who owns it. Use 'unassigned' if nobody was named."},
                "due": {"type": "string", "description": "Deadline as spoken, or 'none'."},
            },
            "required": ["task", "owner", "due"],
        },
    },
    {
        "type": "function",
        "name": "flag_claim",
        "description": "Fact-check a specific number, date or factual claim that was said aloud or is visible on screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "The claim, quoted as closely as possible."},
                "verdict": {"type": "string", "enum": ["supported", "contradicted", "unverifiable"]},
                "evidence": {"type": "string", "description": "One line: the fact from the knowledge file or screen that decides it."},
                "source": {"type": "string", "enum": ["speech", "screen", "both"]},
            },
            "required": ["claim", "verdict", "evidence", "source"],
        },
    },
]


def handle_tool_call(name: str, arguments: str) -> tuple[dict | None, dict]:
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return None, {"ok": False, "error": "bad json"}
    if name == "add_task":
        event = {"type": "task", "task": args.get("task", ""), "owner": args.get("owner", "unassigned"), "due": args.get("due", "none"), "at": time.time()}
        return event, {"ok": True}
    if name == "flag_claim":
        event = {"type": "claim", "claim": args.get("claim", ""), "verdict": args.get("verdict", "unverifiable"), "evidence": args.get("evidence", ""), "source": args.get("source", "speech"), "at": time.time()}
        return event, {"ok": True}
    return None, {"ok": False, "error": f"unknown tool {name}"}
