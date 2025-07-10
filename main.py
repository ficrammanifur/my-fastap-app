from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import json
import uuid
import random
import os
import pyfiglet
import logging
from typing import Dict, List

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Adding CORS middleware for specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ficrammanifur.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage
rooms = {}
connections = {}

# Pydantic models for request validation
class CreateRoomRequest(BaseModel):
    player_name: str

class JoinRoomRequest(BaseModel):
    room_id: str
    player_name: str

@app.get("/")
async def root():
    # Generating ASCII art for "Ludo Backend Running"
    ascii_art = pyfiglet.figlet_format("Ludo Backend Running", font="slant")
    return PlainTextResponse(ascii_art + "\nStatus: running")

@app.get("/health")
async def health():
    return {"status": "healthy", "rooms": len(rooms)}

@app.get("/debug/rooms")
async def debug_rooms():
    """Debug endpoint to list all rooms"""
    return {"rooms": list(rooms.keys())}

@app.post("/create-room")
async def create_room(request: CreateRoomRequest):
    """Buat room baru"""
    logger.info(f"Create room request: {request}")
    player_name = request.player_name
    if not player_name.strip():
        logger.error("Player name is empty")
        return {"error": "Player name cannot be empty"}, 422
    
    room_id = str(uuid.uuid4())[:8].upper()
    
    room_data = {
        "id": room_id,
        "players": [{"id": str(uuid.uuid4()), "name": player_name, "color": "red", "position": 0}],
        "current_turn": 0,
        "game_state": "waiting",
        "dice_result": None,
        "max_players": 4
    }
    
    rooms[room_id] = room_data
    connections[room_id] = []
    logger.info(f"Room created: {room_id}")
    
    return {
        "room_id": room_id,
        "player_id": room_data["players"][0]["id"],
        "message": f"Room {room_id} created!"
    }

@app.post("/join-room")
async def join_room(request: JoinRoomRequest, raw_request: Request):
    """Join room yang sudah ada"""
    logger.info(f"Join room request: {request}")
    try:
        body = await raw_request.json()
        logger.info(f"Raw request body: {body}")
    except:
        logger.error("Failed to parse request body")
    
    room_id = request.room_id.upper()
    player_name = request.player_name
    
    if not room_id.strip() or not player_name.strip():
        logger.error(f"Invalid input: room_id={room_id}, player_name={player_name}")
        return {"detail": "Room ID and player name cannot be empty"}, 422
    
    if room_id not in rooms:
        logger.error(f"Room not found: {room_id}")
        return {"detail": "Room not found"}, 404
    
    room = rooms[room_id]
    if len(room["players"]) >= room["max_players"]:
        logger.error(f"Room full: {room_id}")
        return {"detail": "Room full"}, 400
    
    colors = ["red", "blue", "green", "yellow"]
    player_color = colors[len(room["players"])]
    
    new_player = {
        "id": str(uuid.uuid4()),
        "name": player_name,
        "color": player_color,
        "position": 0
    }
    
    room["players"].append(new_player)
    logger.info(f"Player {player_name} joined room {room_id}")
    
    return {
        "room_id": room_id,
        "player_id": new_player["id"],
        "message": f"Joined room {room_id}!"
    }

@app.get("/room/{room_id}")
async def get_room(room_id: str):
    """Get info room"""
    room_id = room_id.upper()
    if room_id not in rooms:
        logger.error(f"Room not found: {room_id}")
        return {"detail": "Room not found"}, 404
    return {"room": rooms[room_id]}

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    
    room_id = room_id.upper()
    if room_id not in connections:
        connections[room_id] = []
    connections[room_id].append(websocket)
    
    try:
        if room_id in rooms:
            await websocket.send_text(json.dumps({
                "type": "room_update",
                "room": rooms[room_id]
            }))
        
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            logger.info(f"WebSocket message received in room {room_id}: {message}")
            
            if message["action"] == "start_game":
                if room_id in rooms and len(rooms[room_id]["players"]) >= 2:
                    rooms[room_id]["game_state"] = "playing"
                    await broadcast_to_room(room_id, {
                        "type": "game_started",
                        "room": rooms[room_id]
                    })
            
            elif message["action"] == "roll_dice":
                if room_id in rooms:
                    room = rooms[room_id]
                    dice_result = random.randint(1, 6)
                    room["dice_result"] = dice_result
                    
                    current_player = room["players"][room["current_turn"]]
                    current_player["position"] = min(current_player["position"] + dice_result, 100)
                    
                    room["current_turn"] = (room["current_turn"] + 1) % len(room["players"])
                    
                    await broadcast_to_room(room_id, {
                        "type": "dice_rolled",
                        "dice": dice_result,
                        "room": room
                    })
    
    except WebSocketDisconnect:
        if websocket in connections[room_id]:
            connections[room_id].remove(websocket)
        logger.info(f"WebSocket disconnected from room {room_id}")

async def broadcast_to_room(room_id: str, message: dict):
    """Broadcast pesan ke semua client di room"""
    if room_id not in connections:
        return
    
    disconnected = []
    for websocket in connections[room_id]:
        try:
            await websocket.send_text(json.dumps(message))
        except:
            disconnected.append(websocket)
    
    for ws in disconnected:
        connections[room_id].remove(ws)
        logger.info(f"Removed disconnected WebSocket from room {room_id}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
