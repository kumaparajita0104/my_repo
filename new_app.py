import os
import shlex
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify

# -------------------------
# Azure OpenAI client import
# -------------------------
try:
    # new SDK >=1.x (preferred)
    from openai import AzureOpenAI
except Exception as e:
    raise ImportError(
        "AzureOpenAI import failed. Make sure you installed openai>=1.0: "
        "`pip install --upgrade openai`. Original error: " + str(e)
    )

# -------------------------
# CONFIG
# -------------------------
# Path to the MCP CLI executable (adjust if needed)
MCP_CMD = r"C:\Users\Aparajita262593\AppData\Roaming\npm\github-mcp-server.cmd"

# Base directory where repos will be cloned / kept (each repo => subfolder)
BASE_REPO_DIR = Path(r"C:\Users\Aparajita262593\OneDrive - EXLService.com (I) Pvt. Ltd\Documents\mcp_local")

# Allowed MCP tools (whitelist) — add/remove as you trust
ALLOWED_TOOLS = {
    "gbranch", "gcheckout", "gstatus", "gpush", "gpull",
    "gcommit", "glog", "gdiff", "gmerge", "grebase", "gtag","gadd",
    "gclone", "gremote", "greset", "gstash", "gpop", "gflow", "gquick", "gsync"
}

# Azure OpenAI client
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),  # e.g. "https://my-resource.openai.azure.com"
    api_version="2024-08-01-preview"
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")  # required

if not DEPLOYMENT:
    raise RuntimeError("Set AZURE_OPENAI_DEPLOYMENT env var to your deployment name.")

# ensure base dir exists
BASE_REPO_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

# -------------------------
# Helpers
# -------------------------
def clone_repo_if_needed(repo_identifier: str) -> Path:
    """
    If repo_identifier looks like a URL (http or git@), clone it into BASE_REPO_DIR.
    Otherwise treat it as a folder-name under BASE_REPO_DIR and return that path.
    Returns the local repo path (Path).
    """
    repo_identifier = repo_identifier.strip()
    # is URL?
    if repo_identifier.startswith("http://") or repo_identifier.startswith("https://") or repo_identifier.startswith("git@"):
        # derive repo name from URL
        repo_name = repo_identifier.rstrip("/").split("/")[-1].replace(".git", "")
        local_path = BASE_REPO_DIR / repo_name
        if not local_path.exists():
            # clone into local_path
            # If user needs to clone private repo, they must have credentials configured (SSH or token)
            subprocess.run(["git", "clone", repo_identifier, str(local_path)], check=True, cwd=BASE_REPO_DIR)
        return local_path
    else:
        # treat as already cloned folder name
        local_path = BASE_REPO_DIR / repo_identifier
        if not local_path.exists():
            raise FileNotFoundError(f"Local repo path does not exist: {local_path}. "
                                    "Provide a GitHub URL to auto-clone or create the local folder.")
        return local_path

def prompt_to_mcp_command(prompt: str) -> str:
    """
    Ask Azure OpenAI to map the natural prompt to exactly one MCP tool command.
    Enforce short, raw command-only output via system prompt and post-validate it.
    """
    system = (
        "You are a strict translator that converts a short natural-language Git intent "
        "into a single MCP CLI command (one of: " + ", ".join(sorted(ALLOWED_TOOLS)) + ").\n"
        "Output MUST be only the command and arguments, plain text, no markdown, no backticks, "
        "no explanation, no punctuation outside the command, e.g.:\n"
        "gbranch feature-login\n"
        "If the intent is 'commit' or 'push', output: gcommit -m 'USER_MSG' && gpush or just gcommit -m 'USER_MSG'."
        "If the intent requires a repo name, do NOT include a path — we will run the command inside the repo folder.\n"
    )
    user = f"Map this user request to an MCP command: {prompt}"

    res = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        temperature=0.0,
        max_tokens=64
    )

    raw = res.choices[0].message.content.strip()
    # Remove common markdown wrappers if model still included them
    raw = raw.replace("```bash", "").replace("```", "").strip()
    return raw

def validate_and_build_args(raw_cmd: str):
    """
    Validate raw_cmd string (like 'gbranch feature-login') and return a list for subprocess:
    [MCP_CMD, 'gbranch', 'feature-login']
    """
    if not raw_cmd:
        raise ValueError("LLM returned empty command.")
    # split respecting quotes
    tokens = shlex.split(raw_cmd)
    if len(tokens) == 0:
        raise ValueError("No tokens parsed from LLM output.")
    tool = tokens[0]
    if tool not in ALLOWED_TOOLS:
        raise ValueError(f"Tool '{tool}' is not in the allowed list: {sorted(ALLOWED_TOOLS)}")
    # Build final arg list
    return [MCP_CMD] + tokens

def refine_stdout(raw_stdout: str) -> str:
    """
    Generic cleaner for MCP stdout:
    - Strips empty lines
    - Removes common emoji/log prefixes used in MCP output
    - Keeps only 'content' lines likely representing command output
    """
    noise_prefixes = ("📁", "🔗", "🔧", "🌿", "❌", "⚠️", "[", "{", "}")
    lines = raw_stdout.splitlines()
    refined_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue  # skip blank lines
        if any(stripped.startswith(prefix) for prefix in noise_prefixes):
            continue  # skip log/meta lines
        refined_lines.append(stripped)

    # If filtering removed everything fallback to original output
    return "\n".join(refined_lines) if refined_lines else raw_stdout.strip()


# -------------------------
# Route
# -------------------------
@app.route("/mcp", methods=["POST"])
def mcp_endpoint():
    """
    Expected JSON:
    {
        "repository": "https://github.com/you/repo.git" OR "repo_folder_name",
        "prompt": "commit my code",
        "commit_message": "Your commit message here"  # optional, required if committing
    }
    """
    try:
        payload = request.json or {}
        repo_in = payload.get("repository", "").strip()
        user_prompt = payload.get("prompt", "").strip()
        commit_msg = payload.get("commit_message", "").strip()
        print(commit_msg)
        

        if not repo_in:
            return jsonify({"error": "Missing 'repository' in request body. Provide a GitHub URL or local repo folder name."}), 400
        if not user_prompt:
            return jsonify({"error": "Missing 'prompt' in request body."}), 400

        # Ensure repo exists locally (or clone)
        try:
            repo_path = clone_repo_if_needed(repo_in)
        except subprocess.CalledProcessError as e:
            return jsonify({"error": "Git clone failed", "details": str(e)}), 500
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 400

        # Ask LLM for MCP command
        raw_command = prompt_to_mcp_command(user_prompt)
        if raw_command.startswith("gcommit"):
            subprocess.run(
                ["git", "add", "."],
                cwd=str(repo_path),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )


        # Validate and build subprocess arguments
        try:
            mcp_args = validate_and_build_args(raw_command)
        except ValueError as ve:
            return jsonify({"error": "Invalid command from model", "details": str(ve), "raw_model_output": raw_command}), 400
        
        if mcp_args[1] == "gcommit":
            if "-m" not in mcp_args:
                mcp_args.extend(["-m", commit_msg])
            print("Running MCP command:", mcp_args, "in", repo_path)

        # Run MCP command inside the repo path
        proc = subprocess.run(
            mcp_args,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        refined_output = refine_stdout(proc.stdout)

        return jsonify({
            "repository": str(repo_path),
            "prompt": user_prompt,
            "mapped_command": raw_command,
            "mcp_args": mcp_args,
            "returncode": proc.returncode,
            "stdout": refined_output,
            "stderr": proc.stderr
        })

        

    except Exception as e:
        return jsonify({"error": "Unhandled exception", "details": str(e)}), 500

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    app.run(port=5000, debug=True)
