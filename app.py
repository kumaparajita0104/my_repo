from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

GITHUB_API_URL = "https://api.github.com"

@app.route('/mcp/query', methods=['POST'])
def mcp_query():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    token = auth_header.split()[1]
    data = request.get_json()
    repo = data.get("repository")
    question = data.get("question", "").lower()

    if "branches" in question:
        return handle_branches(repo, token)
    else:
        return jsonify({"answer": "Question not supported"}), 400

def handle_branches(repo, token):
    url = f"{GITHUB_API_URL}/repos/{repo}/branches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch branches", "details": response.json()}), 500

    branches = response.json()
    count = len(branches)

    return jsonify({"answer": f"There are {count} branches in the repository."})

if __name__ == '__main__':
    app.run(port=5000, debug=True)
