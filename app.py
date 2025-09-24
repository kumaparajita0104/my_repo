import subprocess
from flask import Flask, request, jsonify
import atexit
import time

app = Flask(__name__)

MCP_CMD = r"C:\Users\Aparajita262593\AppData\Roaming\npm\github-mcp-server.cmd"

# Start MCP server as a subprocess
mcp_process = subprocess.Popen([MCP_CMD], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Make sure MCP server is terminated when Python exits
atexit.register(lambda: mcp_process.terminate())

# Give MCP server a few seconds to start
time.sleep(3)

@app.route("/branches", methods=["POST"])
def get_branches():
    data = request.json
    repo = data.get("repository")
    
    if not repo:
        return jsonify({"error": "Repository not provided"}), 400
    
    try:
        result = subprocess.run(
    [MCP_CMD, "gbranch"], 
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="ignore"
)

        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        print("Return code:", result.returncode)
        
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip()}), 500
        
        branches = result.stdout.strip().splitlines()
        return jsonify({"branches": branches})
    
    except Exception as e:
        print("Exception occurred:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5000)
