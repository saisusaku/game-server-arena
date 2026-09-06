import asyncio
import json
import random
import os
import http.server
import socketserver
import websockets
import string
import socket
import threading

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

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

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
        "connected_webs": set(),
        "use_bots": False,
        "bot_count": 2  # Default jumlah bot
    }
    return code

async def broadcast_to_room(room_code, message_dict):
    if room_code in rooms:
        data_str = json.dumps(message_dict)
        room = rooms[room_code]
        for ws in list(room["connected_webs"]):
            try:
                await ws.send(data_str)
            except:
                room["connected_webs"].discard(ws)

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
                            "playersCount": p_count,
                            "use_bots": r_data["use_bots"],
                            "bot_count": r_data["bot_count"]
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
                    "direction": "up",
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
                        "direction": "up",
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

            # Toggle opsi & jumlah bot oleh host
            if msg_type == "toggle_bots":
                first_player_id = next((pid for pid, p in room["clients"].items() if p["role"] == "player"), None)
                if player_id == first_player_id or room["clients"].get(player_id, {}).get("role") == "admin":
                    room["use_bots"] = data.get("use_bots", False)
                    room["bot_count"] = int(data.get("bot_count", 2))
                continue

            if msg_type == "chat_message":
                if player_id in room["clients"]:
                    sender_name = room["clients"][player_id]["name"]
                    chat_text = data.get("message", "").strip()
                    if chat_text:
                        await broadcast_to_room(current_room_code, {
                            "type": "chat_message",
                            "sender": sender_name,
                            "message": chat_text
                        })
                continue

            if msg_type == "start_game":
                if player_id in room["clients"]:
                    sender = room["clients"][player_id]
                    first_player_id = next((pid for pid, p in room["clients"].items() if p["role"] == "player"), None)
                    is_host_player = (sender["role"] == "player" and player_id == first_player_id)
                    is_admin = (sender["role"] == "admin")

                    if is_admin or is_host_player:
                        total_players = sum(1 for p in room["clients"].values() if p["role"] == "player")
                        if total_players >= 1 or room["use_bots"]:
                            room["game_started"] = True
                            room["game_over"] = False
                            room["winner"] = ""
                            room["bullets"].clear()
                            
                            room["clients"] = {pid: p for pid, p in room["clients"].items() if not p.get("is_bot")}
                            
                            current_time = asyncio.get_running_loop().time()
                            for pid, p in room["clients"].items():
                                if p["role"] == "player":
                                    sx, sy = get_random_safe_spawn()
                                    p["x"] = sx
                                    p["y"] = sy
                                    p["lives"] = 5
                                    p["kills"] = 0
                                    p["invulnerable_until"] = current_time + 3.0

                            # Generate bot sejumlah pilihan host
                            if room["use_bots"]:
                                for i in range(room["bot_count"]):
                                    bot_id = f"bot_{i}_{random.randint(1000,9999)}"
                                    bx, by = get_random_safe_spawn()
                                    room["clients"][bot_id] = {
                                        "name": f"AI Bot {i+1}",
                                        "x": bx, "y": by,
                                        "angle": 0,
                                        "direction": "up",
                                        "color": f"hsl({random.randint(0, 360)}, 80%, 55%)",
                                        "lives": 5,
                                        "kills": 0,
                                        "role": "player",
                                        "is_bot": True,
                                        "bot_target_x": bx,
                                        "bot_target_y": by,
                                        "bot_timer": 0,
                                        "invulnerable_until": current_time + 3.0
                                    }

            elif msg_type == "update" and player_id in room["clients"]:
                p = room["clients"][player_id]
                if room["game_started"] and not room["game_over"] and p["lives"] > 0 and p["role"] == "player" and not p.get("is_bot"):
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
                    p["direction"] = data.get("direction", p.get("direction", "up"))
                
            elif msg_type == "shoot" and player_id in room["clients"]:
                p = room["clients"][player_id]
                if room["game_started"] and not room["game_over"] and p["lives"] > 0 and p["role"] == "player":
                    dx = data.get("dx", 0)
                    dy = data.get("dy", 0)
                    
                    # Spawn peluru sedikit di depan posisi player agar tidak menembus tembok dari dalam badan
                    sx = data.get("x", p["x"]) + dx * 25
                    sy = data.get("y", p["y"]) + dy * 25
                    
                    valid_shot = True
                    for obs in OBSTACLES:
                        if check_line_collision(sx, sy, 4, obs):
                            valid_shot = False
                            break
                    
                    if valid_shot:
                        room["bullets"].append({
                            "x": sx, "y": sy,
                            "dx": dx, "dy": dy,
                            "owner": player_id,
                            "owner_id": player_id,
                            "distance_traveled": 0
                        })
            
            elif msg_type == "reset_game":
                room["game_started"] = False
                room["game_over"] = False
                room["winner"] = ""
                room["bullets"].clear()
                room["clients"] = {pid: p for pid, p in room["clients"].items() if not p.get("is_bot")}
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
            
            if not room["clients"]:
                del rooms[current_room_code]

async def game_loop():
    while True:
        current_time = asyncio.get_running_loop().time()

        for r_code, room in list(rooms.items()):
            if room["game_started"] and not room["game_over"]:
                # --- Logika AI Bot (Memburu Sesama Bot & Pemain) ---
                for pid, p in room["clients"].items():
                    if p.get("is_bot") and p["lives"] > 0:
                        p["bot_timer"] = p.get("bot_timer", 0) - 1
                        if p["bot_timer"] <= 0:
                            p["bot_timer"] = random.randint(25, 60)
                            # Bot mencari target terdekat (bisa pemain atau bot lain)
                            available_targets = [cp for cpid, cp in room["clients"].items() if cp["lives"] > 0 and cpid != pid]
                            if available_targets:
                                chosen = random.choice(available_targets)
                                p["bot_target_x"] = chosen["x"] + random.randint(-20, 20)
                                p["bot_target_y"] = chosen["y"] + random.randint(-20, 20)
                            else:
                                p["bot_target_x"] = random.randint(150, 1050)
                                p["bot_target_y"] = random.randint(150, 650)

                        # Pergerakan mulus bot menuju target dengan dukungan sliding dinding
                        dx = p["bot_target_x"] - p["x"]
                        dy = p["bot_target_y"] - p["y"]
                        dist = (dx**2 + dy**2)**0.5
                        
                        if dist > 8:
                            vx = (dx / dist) * 3.8
                            vy = (dy / dist) * 3.8
                            next_x = p["x"] + vx
                            next_y = p["y"] + vy
                            
                            hit = False
                            for obs in OBSTACLES:
                                if check_line_collision(next_x, next_y, 18, obs):
                                    hit = True
                                    break
                            
                            if not hit:
                                p["x"] = next_x
                                p["y"] = next_y
                            else:
                                # Terapkan uji sumbu terpisah agar bot bisa sliding (geser) di sepanjang dinding/rintangan
                                test_x = next_x
                                test_y = p["y"]
                                if not any(check_line_collision(test_x, test_y, 18, obs) for obs in OBSTACLES):
                                    p["x"] = test_x
                                
                                test_x = p["x"]
                                test_y = next_y
                                if not any(check_line_collision(test_x, test_y, 18, obs) for obs in OBSTACLES):
                                    p["y"] = test_y
                                    
                                # Cari jalur alternatif jika benar-benar terhalang
                                p["bot_target_x"] = random.randint(150, 1050)
                                p["bot_target_y"] = random.randint(150, 650)
                            
                            if abs(dx) > abs(dy):
                                p["direction"] = 'right' if dx > 0 else 'left'
                            else:
                                p["direction"] = 'down' if dy > 0 else 'up'

                        # Bot agresif menembak target terdekat (pemain atau sesama bot)
                        if random.randint(1, 25) == 1:
                            valid_targets = [cp for cpid, cp in room["clients"].items() if cp["lives"] > 0 and cpid != pid]
                            if valid_targets:
                                target = min(valid_targets, key=lambda t: (t["x"] - p["x"])**2 + (t["y"] - p["y"])**2)
                                bdx = target["x"] - p["x"]
                                bdy = target["y"] - p["y"]
                                bdist = (bdx**2 + bdy**2)**0.5
                                if bdist > 0 and bdist < 500:
                                    ndx = bdx / bdist
                                    ndy = bdy / bdist
                                    p["direction"] = 'right' if abs(bdx) > abs(bdy) else ('left' if bdx < 0 else ('down' if bdy > 0 else 'up'))
                                    
                                    # Spawn peluru di depan bot agar tidak menembus tembok
                                    spawn_bx = p["x"] + ndx * 25
                                    spawn_by = p["y"] + ndy * 25
                                    
                                    valid_shot = True
                                    for obs in OBSTACLES:
                                        if check_line_collision(spawn_bx, spawn_by, 4, obs):
                                            valid_shot = False
                                            break
                                            
                                    if valid_shot:
                                        room["bullets"].append({
                                            "x": spawn_bx, "y": spawn_by,
                                            "dx": ndx, "dy": ndy,
                                            "owner": pid,
                                            "owner_id": pid,
                                            "distance_traveled": 0
                                        })

                # --- Update Peluru ---
                for b in room["bullets"][:]:
                    prev_x, prev_y = b["x"], b["y"]
                    
                    speed_multiplier = 15  # Diturunkan agar pergerakan peluru lebih terkontrol
                    target_bullet_x = b["x"] + b["dx"] * speed_multiplier
                    target_bullet_y = b["y"] + b["dy"] * speed_multiplier
                    
                    sub_steps = 10  # Ditingkatkan agar pengecekan tabrakan garis semakin presisi
                    sub_dx = (target_bullet_x - prev_x) / sub_steps
                    sub_dy = (target_bullet_y - prev_y) / sub_steps
                    
                    hit_obstacle = False
                    current_sim_x = prev_x
                    current_sim_y = prev_y
                    
                    for _ in range(sub_steps):
                        current_sim_x += sub_dx
                        current_sim_y += sub_dy
                        
                        for obs in OBSTACLES:
                            if check_line_collision(current_sim_x, current_sim_y, 6, obs):
                                hit_obstacle = True
                                break
                        if hit_obstacle:
                            break
                    
                    b["x"] = current_sim_x
                    b["y"] = current_sim_y
                    
                    step_dist = ((b["x"] - prev_x)**2 + (b["y"] - prev_y)**2)**0.5
                    b["distance_traveled"] = b.get("distance_traveled", 0) + step_dist
                    
                    if hit_obstacle or b["distance_traveled"] > 200 or not (0 <= b["x"] <= 1200 and 0 <= b["y"] <= 800):
                        room["bullets"].remove(b)
                        continue
                        
                    hit = False
                    for pid, p in room["clients"].items():
                        if p["lives"] > 0 and pid != b.get("owner"):
                            if current_time < p.get("invulnerable_until", 0):
                                continue

                            dist = ((b["x"] - p["x"])**2 + ((b["y"] - p["y"]))**2)**0.5
                            if dist < 18:
                                p["lives"] -= 1
                                hit = True
                                
                                owner_key = b.get("owner")
                                if owner_key in room["clients"]:
                                    room["clients"][owner_key]["kills"] += 1
                                
                                if p["lives"] > 0:
                                    new_x, new_y = get_random_safe_spawn()
                                    p["x"], p["y"] = new_x, new_y
                                    # Tambahan waktu kebal 3 detik saat respawn aktif
                                    p["invulnerable_until"] = current_time + 8.0
                                break
                    if hit and b in room["bullets"]:
                        room["bullets"].remove(b)

                active_players = [p for p in room["clients"].values() if p["role"] == "player" and p["lives"] > 0]
                total_players = [p for p in room["clients"].values() if p["role"] == "player"]
                
                if len(total_players) >= 1 and not room["game_over"]:
                    if len(active_players) <= 1:
                        room["game_over"] = True
                        if len(active_players) == 1:
                            room["winner"] = f"Pemenang: {active_players[0]['name']} (Bertahan hidup)"
                        else:
                            # Jika semua habis nyawanya (misal mati bersamaan), urutkan berdasarkan kill terbanyak
                            sorted_players = sorted(total_players, key=lambda x: x["kills"], reverse=True)
                            if sorted_players:
                                top_kill = sorted_players[0]["kills"]
                                room["winner"] = f"Pemenang (Top Kill): {sorted_players[0]['name']} ({top_kill} Kill)"
                            else:
                                room["winner"] = "Seri"

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
                    "obstacles": OBSTACLES,
                    "use_bots": room["use_bots"],
                    "bot_count": room["bot_count"]
                })
                
                for ws in list(room["connected_webs"]):
                    try:
                        await ws.send(state)
                    except:
                        room["connected_webs"].discard(ws)
            
        await asyncio.sleep(0.03)

def run_http_server():
    if os.path.exists("static"):
        os.chdir("static")
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", 8080), handler) as httpd:
        local_ip = get_local_ip()
        print(f"[HTTP] Web Server berjalan di:")
        print(f"       -> Local:   http://localhost:8080")
        print(f"       -> Network: http://{local_ip}:8080")
        httpd.serve_forever()

async def main():
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    port = int(os.environ.get("PORT", 8765))

    async with websockets.serve(game_handler, "0.0.0.0", port):
        print(f"[WS] WebSocket Server aktif di port {port} (Multi-Room)")
        await game_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SERVER] Server dihentikan.")