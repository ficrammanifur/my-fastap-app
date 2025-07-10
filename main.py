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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ficrammanifur.github.io", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage
rooms: Dict[str, dict] = {}
connections: Dict[str, List[WebSocket]] = {}

# Pydantic models
class CreateRoomRequest(BaseModel):
    player_name: str

class JoinRoomRequest(BaseModel):
    room_id: str
    player_name: str

@app.get("/")
async def root():
    ascii_art = pyfiglet.figlet_format("Ludo Backend Running", font="slant")
    return PlainTextResponse(ascii_art + "\nStatus: running")

@app.get("/health")
async def health():
    return {"status": "healthy", "rooms": len(rooms)}

@app.get("/debug/rooms")
async def debug_rooms():
    return {"rooms": list(rooms.keys())}

@app.post("/create-room")
async def create_room(request: CreateRoomRequest):
    logger.info(f"Create room request: {request}")
    player_name = request.player_name.strip()
    if not player_name:
        logger.error("Player name is empty")
        return {"detail": "Player name cannot be empty"}, 422
    
    room_id = str(uuid.uuid4())[:8].upper()
    room_data = {
        "id": room_id,
        "players": [{
            "id": str(uuid.uuid4()),
            "name": player_name,
            "color": "red",
            "pieces": [
                {"id": f"{player_name}-r1", "position": "home", "index": 0, "home": True},
                {"id": f"{player_name}-r2", "position": "home", "index": 0, "home": True},
                {"id": f"{player_name}-r3", "position": "home", "index": 0, "home": True},
                {"id": f"{player_name}-r4", "position": "home", "index": 0, "home": True},
            ],
        }],
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
    logger.info(f"Join room request: {request}")
    room_id = request.room_id.upper().strip()
    player_name = request.player_name.strip()
    
    if not room_id or not player_name:
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
        "pieces": [
            {"id": f"{player_name}-{player_color}1", "position": "home", "index": 0, "home": True},
            {"id": f"{player_name}-{player_color}2", "position": "home", "index": 0, "home": True},
            {"id": f"{player_name}-{player_color}3", "position": "home", "index": 0, "home": True},
            {"id": f"{player_name}-{player_color}4", "position": "home", "index": 0, "home": True},
        ],
    }
    
    room["players"].append(new_player)
    logger.info(f"Player {player_name} joined room {room_id}")
    
    await broadcast_to_room(room_id, {
        "type": "room_update",
        "room": room
    })
    
    return {
        "room_id": room_id,
        "player_id": new_player["id"],
        "message": f"Joined room {room_id}!"
    }

@app.get("/room/{room_id}")
async def get_room(room_id: str):
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
                    current_player = room["players"][room["current_turn"]]
                    if current_player["id"] == message["player_id"]:
                        dice_result = random.randint(1, 6)
                        room["dice_result"] = dice_result
                        await broadcast_to_room(room_id, {
                            "type": "dice_rolled",
                            "dice": dice_result,
                            "room": room
                        })
            
            elif message["action"] == "move_piece":
                if room_id in rooms:
                    room = rooms[room_id]
                    current_player = room["players"][room["current_turn"]]
                    if current_player["id"] == message["player_id"]:
                        piece_id = message["piece_id"]
                        dice_result = room["dice_result"]
                        piece = next((p for p in current_player["pieces"] if p["id"] == piece_id), None)
                        if piece:
                            start_pos = {"red": 1, "blue": 40, "green": 14, "yellow": 27}
                            safe_squares = [1, 9, 14, 22, 27, 35, 40, 48]
                            home_entry = 51
                            final_home = 57
                            extra_turn = False

                            if piece["home"] and dice_result == 6:
                                piece["position"] = start_pos[current_player["color"]]
                                piece["index"] = start_pos[current_player["color"]]
                                piece["home"] = False
                                extra_turn = True
                            elif not piece["home"]:
                                new_index = (piece["index"] + dice_result) % 52 if piece["index"] + dice_result <= home_entry else piece["index"] + dice_result
                                if new_index > final_home:
                                    new_index = final_home
                                piece["position"] = (
                                    str(new_index) if new_index <= home_entry else
                                    f"rf{new_index}" if current_player["color"] == "red" else
                                    f"bf{new_index}" if current_player["color"] == "blue" else
                                    f"gf{new_index}" if current_player["color"] == "green" else
                                    f"yf{new_index}"
                                )
                                piece["index"] = new_index
                                if piece["index"] == final_home:
                                    extra_turn = True
                                if piece["index"] not in safe_squares and piece["index"] <= home_entry:
                                    for opponent in room["players"]:
                                        if opponent["id"] != current_player["id"]:
                                            for opp_piece in opponent["pieces"]:
                                                if opp_piece["index"] == piece["index"] and not opp_piece["home"]:
                                                    opp_piece["index"] = 0
                                                    opp_piece["position"] = "home"
                                                    opp_piece["home"] = True
                                                    extra_turn = True
                            
                            if all(p["index"] == final_home for p in current_player["pieces"]):
                                room["game_state"] = "finished"
                                await broadcast_to_room(room_id, {
                                    "type": "game_won",
                                    "winner": current_player["name"],
                                    "room": room
                                })
                            
                            room["current_turn"] = room["current_turn"] if dice_result == 6 or extra_turn else (room["current_turn"] + 1) % len(room["players"])
                            room["dice_result"] = None
                            
                            await broadcast_to_room(room_id, {
                                "type": "piece_moved",
                                "room": room
                            })
    
    except WebSocketDisconnect:
        if websocket in connections[room_id]:
            connections[room_id].remove(websocket)
        logger.info(f"WebSocket disconnected from room {room_id}")

async def broadcast_to_room(room_id: str, message: dict):
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
