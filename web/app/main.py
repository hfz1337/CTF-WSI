#!/usr/bin/python3
import os
from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient

# Load environment variables
MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE = os.getenv("DATABASE")
COLLECTION = os.getenv("COLLECTION")

# MongoDB handle
mongo = MongoClient(MONGODB_URI, connect=False)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.route("/", methods=["GET"])
def search():
    query = request.args.get("q")
    if query is None:
        return render_template("index.html")

    limit = request.args.get("limit")
    limit = min(int(limit), 50) if limit and limit.isdigit() and int(limit) > 0 else 50

    results = list(
        mongo[DATABASE][COLLECTION]
        .find(
            {"$text": {"$search": query}},
            {
                "score": {"$meta": "textScore"},
                "_id": False,
                "ctftime_content": False,
                "blog_content": False,
            },
            sort=[("score", {"$meta": "textScore"})],
        )
        .limit(limit)
    )
    return jsonify(results), 200
