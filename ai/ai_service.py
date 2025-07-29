from flask import Flask, request, jsonify
import cohere
import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

app = Flask(__name__)


COHERE_API_KEY = os.getenv("COHERE_API_KEY")
co = cohere.Client(COHERE_API_KEY)

@app.route("/get_response", methods=["POST"])
def get_response():
    data = request.json
    message = data.get("message")
    
    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        # Removed model parameter here
        response = co.chat(message=message)
        reply = response.text
        return jsonify({"reply": reply})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
