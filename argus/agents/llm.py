"""Model wrapper."""

from __future__ import annotations

import asyncio
import contextlib
import os
import json
import subprocess

from argus.config import llm_config

# -- Claude -----------------------------------------------------------------

_PAID_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")

@contextlib.contextmanager
def _claude_env():
    saved = {k: os.environ.pop(k) for k in _PAID_VARS if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)

async def _run_claude(prompt: str, system: str, model: str) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    options = ClaudeAgentOptions(model=model, system_prompt=system, allowed_tools=[], max_turns=1)
    result = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result = message.result or ""
    return result

def ruminate_claude(prompt: str, system: str, model: str) -> str:
    with _claude_env():
        return asyncio.run(_run_claude(prompt, system, model))

# -- Gemini -----------------------------------------------------------------

def ruminate_gemini(prompt: str, system: str, model: str) -> str:
    import tempfile
    import json
    import subprocess
    
    # We must explicitly tell the CLI to ignore the local workspace context
    # it automatically injects, otherwise it acts like an agent reviewing code.
    firmware_override = (
        f"{system}\n\n"
        "CRITICAL RULE: You are NOT an engineering agent. You are NOT reviewing code. "
        "IGNORE all file paths, project structures, and code context automatically provided to you. "
        "Answer ONLY the user's prompt based strictly on the system role defined above."
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(firmware_override)
        sys_prompt_path = f.name

    env = os.environ.copy()
    env["GEMINI_SYSTEM_MD"] = sys_prompt_path

    cmd = [
        "gemini", 
        "-p", prompt,
        "--output-format", "json", 
        "--raw-output", 
        "--accept-raw-output-risk"
    ]
    if model and model not in {"opus", "gemini-1.5-pro"}:
        cmd.extend(["-m", model])
        
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        output = res.stdout.strip()
        start = output.find("{")
        if start == -1:
            return f"(Error: Gemini CLI returned no JSON: {output})"
        return json.loads(output[start:])["response"]
    except subprocess.CalledProcessError as exc:
        return f"(Error: Gemini CLI failed: {exc.stderr or exc.stdout})"
    except Exception as exc:
        return f"(Error: Failed to call Gemini CLI: {exc})"
    finally:
        if os.path.exists(sys_prompt_path):
            os.remove(sys_prompt_path)

# -- Ollama (Local) ---------------------------------------------------------

def ruminate_ollama(prompt: str, system: str, model: str) -> str:
    import urllib.request
    import json
    
    # Default to llama3 if not specified
    model_name = model if model and model != "opus" else "llama3"
    
    url = "http://localhost:11434/api/chat"
    data = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode("utf-8"), 
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("message", {}).get("content", "")
    except urllib.error.URLError as exc:
        return f"(Error: Could not connect to Ollama at {url}. Is it running? {exc})"
    except Exception as exc:
        return f"(Error: Failed to call Ollama: {exc})"

def ruminate(prompt: str, system: str) -> str:
    config = llm_config()
    if config.provider == "ollama":
        return ruminate_ollama(prompt, system, config.model)
    if config.provider == "gemini":
        return ruminate_gemini(prompt, system, config.model)
    return ruminate_claude(prompt, system, config.model)
