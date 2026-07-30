#!/usr/bin/env python3
"""
iOS Shortcuts MCP Server (Zero-Dependency Stdio MCP Server)
Enables AI Agents (Gemini, Claude, Cursor, Antigravity) to create, sign, import, list, run, and send iOS Shortcuts on macOS.
"""

import sys
import json
import os
import subprocess
from shortcut_builder import build_shortcut_plist

SERVER_NAME = "ios-shortcuts-mcp"
SERVER_VERSION = "1.0.0"

TOOLS = [
    {
        "name": "build_shortcut",
        "description": "Create a macOS/iOS .shortcut binary plist file from high-level action recipes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the shortcut (e.g., '퇴근 개선')"
                },
                "actions": {
                    "type": "array",
                    "description": "List of action dictionaries (e.g., date, open_app, delay, speak_text, set_volume, etc.)"
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory path (optional, defaults to ./dist)"
                }
            },
            "required": ["name", "actions"]
        }
    },
    {
        "name": "sign_shortcut",
        "description": "Sign an un-signed .shortcut file using macOS native 'shortcuts sign -m anyone' CLI for iOS 15+ compatibility.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Path to the input .shortcut file"
                },
                "output_path": {
                    "type": "string",
                    "description": "Path where the signed .shortcut file will be saved"
                }
            },
            "required": ["input_path", "output_path"]
        }
    },
    {
        "name": "import_shortcut",
        "description": "Import/install a .shortcut file directly into the macOS Shortcuts library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "shortcut_path": {
                    "type": "string",
                    "description": "Path to the .shortcut file to import"
                }
            },
            "required": ["shortcut_path"]
        }
    },
    {
        "name": "list_shortcuts",
        "description": "List all installed Shortcuts on this Mac.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "run_shortcut",
        "description": "Run an installed Shortcut by name on macOS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the shortcut to run"
                },
                "input_text": {
                    "type": "string",
                    "description": "Optional input text to pass to the shortcut"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "send_imessage",
        "description": "Send a file or shortcut via iMessage/Email using macOS native Message/Mail capabilities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Email address or phone number of the recipient"
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to the file or .shortcut to attach"
                },
                "message": {
                    "type": "string",
                    "description": "Optional text message to send"
                }
            },
            "required": ["recipient", "file_path"]
        }
    }
]

def handle_tool_call(tool_name: str, arguments: dict) -> dict:
    try:
        if tool_name == "build_shortcut":
            name = arguments.get("name")
            actions = arguments.get("actions", [])
            output_dir = arguments.get("output_dir", "./dist")
            saved_path = build_shortcut_plist(actions, name, output_dir)
            return {
                "content": [{
                    "type": "text",
                    "text": f"Successfully created and signed shortcut '{name}' at path: {saved_path}"
                }]
            }

        elif tool_name == "sign_shortcut":
            inp = arguments.get("input_path")
            outp = arguments.get("output_path")
            res = subprocess.run(["shortcuts", "sign", "-m", "anyone", "-i", inp, "-o", outp], capture_output=True, text=True)
            if res.returncode == 0:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Successfully signed shortcut saved to: {outp}"
                    }]
                }
            else:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Signing error: {res.stderr}"
                    }],
                    "isError": True
                }

        elif tool_name == "import_shortcut":
            path = arguments.get("shortcut_path")
            res = subprocess.run(["open", path], capture_output=True, text=True)
            return {
                "content": [{
                    "type": "text",
                    "text": f"Triggered import opening for shortcut: {path}"
                }]
            }

        elif tool_name == "list_shortcuts":
            res = subprocess.run(["shortcuts", "list"], capture_output=True, text=True)
            return {
                "content": [{
                    "type": "text",
                    "text": res.stdout if res.returncode == 0 else f"Error listing shortcuts: {res.stderr}"
                }]
            }

        elif tool_name == "run_shortcut":
            name = arguments.get("name")
            inp = arguments.get("input_text")
            cmd = ["shortcuts", "run", name]
            res = subprocess.run(cmd, input=inp, capture_output=True, text=True)
            return {
                "content": [{
                    "type": "text",
                    "text": f"Output from shortcut '{name}':\n{res.stdout}" if res.returncode == 0 else f"Error running shortcut: {res.stderr}"
                }]
            }

        elif tool_name == "send_imessage":
            rec = arguments.get("recipient")
            path = os.path.abspath(arguments.get("file_path"))
            msg = arguments.get("message", "Shortcut file attached.")
            
            # Open iMessage URI & Finder
            subprocess.run(["open", f"imessage://{rec}"])
            subprocess.run(["open", "-R", path])
            
            return {
                "content": [{
                    "type": "text",
                    "text": f"Opened iMessage compose window for {rec} and highlighted file {path} in Finder."
                }]
            }

        else:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True
            }
            
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Exception in tool execution: {str(e)}"}],
            "isError": True
        }

def respond_json(response_obj):
    json_str = json.dumps(response_obj)
    sys.stdout.write(json_str + "\n")
    sys.stdout.flush()

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
            
        try:
            req = json.loads(line)
        except Exception:
            continue
            
        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})
        
        if method == "initialize":
            respond_json({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION
                    }
                }
            })
            
        elif method == "notifications/initialized":
            # No response needed
            pass
            
        elif method == "tools/list":
            respond_json({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": TOOLS
                }
            })
            
        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            result = handle_tool_call(tool_name, args)
            respond_json({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result
            })
            
        elif method == "ping":
            respond_json({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {}
            })
            
        else:
            if msg_id is not None:
                respond_json({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                })

if __name__ == "__main__":
    main()
