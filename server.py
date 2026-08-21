import asyncio
import json
import random
import os
import websockets
import string

# Struktur data per lobi (Rooms)
rooms = {}

OBSTACLES = [
    {"x1": 500, "y1": 400, "x2": 700, "y2": 400},
    {"x1": 600, "y1": 300, "x2": 600, "y2": 500},
    {"x1": 300, "y1": 200, "x2": 900, "y2": 200},
    {"x1": 300, "y1": 600, "x2": 900, "y2": 600},
    {"x1": 300, "y1": 200, "x2": 300, "y2": 300},
    {"x1": 900, "y1": 200, "x2": 900, "y2": 300},
    {"x1": 300, "y1": 500, "x2": 300, "y2": 600},
    {"x1": 900, "y1": 500, "x2": 900, "y2": 600},
    {"x1": 150, "y1": 150, "x2": 150, "y2": 250},
    {"x1": 1050, "y1": 550, "x2": 1050, "y2": 650},
    {"x1": 150, "y1": 650, "x2": 250, "y2": 650},
    {"x1": 950, "y1": 150, "x2": 1050, "y2": 150},
]

def check_line_collision(x, y, radius, line):
    x1, y1, x2, y2 = line["x1"], line["y1"], line["x2"], line["y2"]
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx*dx + dy*dy
    if length_sq == 0:
        return ((x - x1)**2 + (y - y1)**2)**0.5 < radius
    
    t = ((x - x1) * dx + (y - y1) * dy) / length_sq
    t = max(0, min(1, t))
    
    nearest_x = x1 + t * dx
    nearest_y = y1 + t * dy
    
    dist_sq = (x - nearest_x)**2 + (y - nearest_y)**2
    return dist_sq < (radius**2)

def get_random_safe_spawn():
    while True:
        rx = random.randint(100, 1100)
        ry = random.randint(100, 700)
        collision = False
        for obs in OBSTACLES:
            if check_line_collision(rx, ry, 25, obs):
                collision = True
                break
        if not collision:
            return rx, ry

def create_new_room():
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
        if code not in rooms:
            break
    rooms[code] = {
        "clients": {},
        "bullets": [],
        "game_started": False,
        "game_over": False,
        "winner": "",
        "connected_webs": set()
    }
    return code

async def game_handler(websocket):
    player_id = str(id(websocket))
    current_room_code = None
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue
            
            msg_type = data.get("type")
            
            if msg_type == "get_rooms":
                room_list = []
                for r_code, r_data in rooms.items():
                    p_count = sum(1 for p in r_data["clients"].values() if p["role"] == "player")
                    if not r_data["game_started"]:
                        room_list.append({
                            "id": r_code,
                            "name": f"Lobi ({r_code})",
                            "playersCount": p_count
                        })
                await websocket.send(json.dumps({
                    "type": "room_list",
                    "rooms": room_list
                }))
                continue
            
            if msg_type == "login":
                requested_role = data.get("role", "player")
                name = data.get("name", "Player")
                role = "admin" if requested_role == "admin" else "player"
                
                current_room_code = create_new_room()
                room = rooms[current_room_code]
                room["connected_webs"].add(websocket)
                
                color = f"hsl({random.randint(0, 360)}, 70%, 50%)"
                spawn_x, spawn_y = get_random_safe_spawn()
                current_time = asyncio.get_running_loop().time()
                
                room["clients"][player_id] = {
                    "name": name,
                    "x": spawn_x, "y": spawn_y,
                    "angle": 0,
                    "color": color,
                    "lives": 5,
                    "kills": 0,
                    "role": role,
                    "invulnerable_until": current_time + 3.0
                }
                
            elif msg_type == "join_room":
                target_room = data.get("room_id")
                name = data.get("name", "Player")
                
                if target_room in rooms and not rooms[target_room]["game_started"]:
                    current_room_code = target_room
                    room = rooms[current_room_code]
                    room["connected_webs"].add(websocket)
                    
                    color = f"hsl({random.randint(0, 360)}, 70%, 50%)"
                    spawn_x, spawn_y = get_random_safe_spawn()
                    current_time = asyncio.get_running_loop().time()
                    
                    room["clients"][player_id] = {
                        "name": name,
                        "x": spawn_x, "y": spawn_y,
                        "angle": 0,
                        "color": color,
                        "lives": 5,
                        "kills": 0,
                        "role": "player",
                        "invulnerable_until": current_time + 3.0
                    }
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Lobi tidak ditemukan atau sudah mulai!"}))
                    continue

            if not current_room_code or current_room_code not in rooms:
                continue
            
            room = rooms[current_room_code]

            if msg_type == "start_game":
                if player_id in room["clients"]:
                    sender = room["clients"][player_id]
                    first_player_id = next((pid for pid, p in room["clients"].items() if p["role"] == "player"), None)
                    is_host_player = (sender["role"] == "player" and player_id == first_player_id)
                    is_admin = (sender["role"] == "admin")

                    if is_admin or is_host_player:
                        total_players = sum(1 for p in room["clients"].values() if p["role"] == "player")
                        if total_players >= 2:
                            room["game_started"] = True
                            room["game_over"] = False
                            room["winner"] = ""
                            room["bullets"].clear()
                            
                            current_time = asyncio.get_running_loop().time()
                            for pid, p in room["clients"].items():
                                if p["role"] == "player":
                                    sx, sy = get_random_safe_spawn()
                                    p["x"] = sx
                                    p["y"] = sy
                                    p["lives"] = 5
                                    p["kills"] = 0
                                    p["invulnerable_until"] = current_time + 3.0

            elif msg_type == "update" and player_id in room["clients"]:
                p = room["clients"][player_id]
                if room["game_started"] and not room["game_over"] and p["lives"] > 0 and p["role"] == "player":
                    target_x, target_y = data.get("x", p["x"]), data.get("y", p["y"])
                    current_x, current_y = p["x"], p["y"]
                    
                    max_step = 10
                    dist = ((target_x - current_x)**2 + (target_y - current_y)**2)**0.5
                    if dist > max_step * 2:
                        target_x = current_x + (target_x - current_x) * (max_step / dist)
                        target_y = current_y + (target_y - current_y) * (max_step / dist)

                    hit = False
                    for obs in OBSTACLES:
                        if check_line_collision(target_x, target_y, 18, obs):
                            hit = True
                            break
                    
                    if not hit:
                        p["x"] = target_x
                        p["y"] = target_y
                    else:
                        test_x = target_x
                        test_y = current_y
                        if not any(check_line_collision(test_x, test_y, 18, obs) for obs in OBSTACLES):
                            p["x"] = test_x
                        
                        test_x = p["x"]
                        test_y = target_y
                        if not any(check_line_collision(test_x, test_y, 18, obs) for obs in OBSTACLES):
                            p["y"] = test_y

                    p["angle"] = data.get("angle", 0)
                
            elif msg_type == "shoot" and player_id in room["clients"]:
                p = room["clients"][player_id]
                if room["game_started"] and not room["game_over"] and p["lives"] > 0 and p["role"] == "player":
                    sx = data.get("x", p["x"])
                    sy = data.get("y", p["y"])
                    valid_shot = True
                    for obs in OBSTACLES:
                        if check_line_collision(sx, sy, 4, obs):
                            valid_shot = False
                            break
                    
                    if valid_shot:
                        room["bullets"].append({
                            "x": sx, "y": sy,
                            "dx": data.get("dx", 0), "dy": data.get("dy", 0),
                            "owner": player_id,
                            "distance_traveled": 0
                        })
            
            elif msg_type == "reset_game":
                room["game_started"] = False
                room["game_over"] = False
                room["winner"] = ""
                room["bullets"].clear()
                for pid, p in room["clients"].items():
                    p["lives"] = 5
                    p["kills"] = 0

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[ERROR]: {e}")
    finally:
        if current_room_code and current_room_code in rooms:
            room = rooms[current_room_code]
            if websocket in room["connected_webs"]:
                room["connected_webs"].remove(websocket)
            if player_id in room["clients"]:
                del room["clients"][player_id]
            
            if not room["clients"] or not any(p["role"] == "admin" for p in room["clients"].values()):
                del rooms[current_room_code]

async def game_loop():
    while True:
        current_time = asyncio.get_running_loop().time()

        for r_code, room in list(rooms.items()):
            if room["game_started"] and not room["game_over"]:
                for b in room["bullets"][:]:
                    prev_x, prev_y = b["x"], b["y"]
                    b["x"] += b["dx"] * 9
                    b["y"] += b["dy"] * 9
                    
                    step_dist = ((b["x"] - prev_x)**2 + (b["y"] - prev_y)**2)**0.5
                    b["distance_traveled"] = b.get("distance_traveled", 0) + step_dist
                    
                    if b["distance_traveled"] > 250 or not (0 <= b["x"] <= 1200 and 0 <= b["y"] <= 800):
                        room["bullets"].remove(b)
                        continue
                        
                    hit_obstacle = False
                    for obs in OBSTACLES:
                        if check_line_collision(b["x"], b["y"], 4, obs):
                            hit_obstacle = True
                            break
                    if hit_obstacle:
                        room["bullets"].remove(b)
                        continue
                        
                    hit = False
                    for pid, p in room["clients"].items():
                        if p["role"] == "player" and p["lives"] > 0 and pid != b["owner"]:
                            if current_time < p.get("invulnerable_until", 0):
                                continue

                            dist = ((b["x"] - p["x"])**2 + (b["y"] - p["y"])**2)**0.5
                            if dist < 18:
                                p["lives"] -= 1
                                hit = True
                                
                                if b["owner"] in room["clients"]:
                                    room["clients"][b["owner"]]["kills"] += 1
                                
                                if p["lives"] > 0:
                                    new_x, new_y = get_random_safe_spawn()
                                    p["x"], p["y"] = new_x, new_y
                                    p["invulnerable_until"] = current_time + 3.0
                                break
                    if hit and b in room["bullets"]:
                        room["bullets"].remove(b)

                active_players = [p for p in room["clients"].values() if p["role"] == "player" and p["lives"] > 0]
                total_players = [p for p in room["clients"].values() if p["role"] == "player"]
                
                if len(total_players) >= 1 and not room["game_over"]:
                    if len(active_players) <= 1:
                        room["game_over"] = True
                        room["winner"] = active_players[0]["name"] if len(active_players) == 1 else "Seri"

            if room["connected_webs"]:
                export_clients = {}
                for pid, p in room["clients"].items():
                    p_copy = p.copy()
                    p_copy["is_invulnerable"] = p.get("invulnerable_until", 0) > current_time
                    export_clients[pid] = p_copy

                state = json.dumps({
                    "room_id": r_code,
                    "room_code": r_code,
                    "game_started": room["game_started"],
                    "game_over": room["game_over"],
                    "winner": room["winner"],
                    "clients": export_clients,
                    "bullets": room["bullets"],
                    "obstacles": OBSTACLES
                })
                
                for ws in list(room["connected_webs"]):
                    try:
                        await ws.send(state)
                    except:
                        room["connected_webs"].discard(ws)
            
        await asyncio.sleep(0.03)

async def main():
    port = int(os.environ.get("PORT", 8765))
    async with websockets.serve(game_handler, "0.0.0.0", port):
        print(f"[WS] WebSocket Server aktif di port {port} (Multi-Room)")
        await game_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SERVER] Server dihentikan.")