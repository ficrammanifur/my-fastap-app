from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
import json
import uuid
import random
import os
import pyfiglet
from typing import Dict, List

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

@app.get("/")
async def root():
    # Generating ASCII art for "Ludo Backend Running"
    ascii_art = pyfiglet.figlet_format("Ludo Backend Running", font="slant")
    return PlainTextResponse(ascii_art + "\nStatus: running")

@app.get("/health")
async def health():
    return {"status": "healthy", "rooms": len(rooms)}

@app.post("/create-room")
async def create_room(player_name: str):
    """Buat room baru"""
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
    
    return {
        "room_id": room_id,
        "player_id": room_data["players"][0]["id"],
        "message": f"Room {room_id} created!"
    }

@app.post("/join-room")
async def join_room(room_id: str, player_name: str):
    """Join room yang sudah ada"""
    if room_id not in rooms:
        return {"error": "Room not found"}, 404
    
    room = rooms[room_id]
    if len(room["players"]) >= room["max_players"]:
        return {"error": "Room full"}, 400
    
    colors = ["red", "blue", "green", "yellow"]
    player_color = colors[len(room["players"])]
    
    new_player = {
        "id": str(uuid.uuid4()),
        "name": player_name,
        "color": player_color,
        "position": 0
    }
    
    room["players"].append(new_player)
    
    return {
        "room_id": room_id,
        "player_id": new_player["id"],
        "message": f"Joined room {room_id}!"
    }

@app.get("/room/{room_id}")
async def get_room(room_id: str):
    """Get info room"""
    if room_id not in rooms:
        return {"error": "Room not found"}, 404
    return {"room": rooms[room_id]}

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    
    if room_id not in connections:
        connections[room_id] = []
    connections[room_id].append(websocket)
    
    try:
        # Kirim room state saat connect
        if room_id in rooms:
            await websocket.send_text(json.dumps({
                "type": "room_update",
                "room": rooms[room_id]
            }))
        
        while True:
            # Terima pesan dari client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle actions
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
                    
                    # Update posisi player (simplified)
                    current_player = room["players"][room["current_turn"]]
                    current_player["position"] = min(current_player["position"] + dice_result, 100)
                    
                    # Next turn
                    room["current_turn"] = (room["current_turn"] + 1) % len(room["players"])
                    
                    await broadcast_to_room(room_id, {
                        "type": "dice_rolled",
                        "dice": dice_result,
                        "room": room
                    })
    
    except WebSocketDisconnect:
        if websocket in connections[room_id]:
            connections[room_id].remove(websocket)

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
    
    # Remove disconnected websockets
    for ws in disconnected:
        connections[room_id].remove(ws)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Use Railway's PORT or default to 8000
    uvicorn.run(app, host="0.0.0.0", port=port)
