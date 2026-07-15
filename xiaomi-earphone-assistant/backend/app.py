from flask import Flask, jsonify, render_template

app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static",
)

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/health")
def health():
    return jsonify({"success": True, "message": "service is running"})

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
