import os
import socket
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator


TEAMS = [
    "Mumbai Indians",
    "Chennai Super Kings",
    "Royal Challengers Bengaluru",
    "Kolkata Knight Riders",
    "Delhi Capitals",
    "Rajasthan Royals",
    "Sunrisers Hyderabad",
    "Punjab Kings",
    "Lucknow Super Giants",
    "Gujarat Titans"
]

MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI environment variable is not set")


while True:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        print("Connected to MongoDB")
        break
    except ServerSelectionTimeoutError:
        print("Waiting for MongoDB...")
        time.sleep(2)

db = client["ipl_voter"]
votes_collection = db["votes"]

def init_db():
    for team in TEAMS:
        votes_collection.update_one(
            {"team": team},
            {"$setOnInsert": {"count": 0}},
            upsert=True
        )
        
@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, votes_collection

    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI environment variable is not set")

    client = MongoClient(mongo_uri)
    client.admin.command("ping")

    db = client["ipl_voter"]
    votes_collection = db["votes"]

    init_db()

    yield

    client.close()

app = FastAPI(title="IPL Team Voter", lifespan=lifespan)

templates = Jinja2Templates(directory="templates")

# Prometheus
Instrumentator().instrument(app).expose(app)

vote_counter = Counter(
    "votes_total",
    "Total number of votes cast",
    ["team"]
)


def get_votes():
    rows = votes_collection.find({}, {"_id": 0}).sort("count", -1)
    return {row["team"]: row["count"] for row in rows}


def increment_vote(team):
    votes_collection.update_one(
        {"team": team},
        {"$inc": {"count": 1}}
    )


@app.get("/")
def home():
    votes = get_votes()

    return {
        "app": "IPL Team Voter",
        "pod": socket.gethostname(),
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "total_votes": sum(votes.values()),
        "teams": list(votes.keys())
    }


@app.post("/vote/{team_name}")
def vote(team_name: str):

    votes = get_votes()

    matched = next(
        (
            team
            for team in votes
            if team.lower().replace(" ", "-") == team_name.lower()
        ),
        None,
    )

    if not matched:
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Team '{team_name}' not found",
                "valid_teams": list(votes.keys())
            }
        )

    increment_vote(matched)
    vote_counter.labels(team=matched).inc()

    updated = get_votes()

    return {
        "message": f"Vote cast for {matched}!",
        "total_votes_for_team": updated[matched]
    }


@app.get("/results")
def results():
    votes = get_votes()

    leaderboard = sorted(
        votes.items(),
        key=lambda x: x[1],
        reverse=True
    )

    winner = (
        leaderboard[0][0]
        if leaderboard and leaderboard[0][1] > 0
        else "No votes yet!"
    )

    return {
        "winner": winner,
        "leaderboard": [
            {"team": team, "votes": count}
            for team, count in leaderboard
        ]
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"status": "ready"}

@app.get("/ui", response_class=HTMLResponse)
def ui(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "IPL Team Voter"
        }
    )