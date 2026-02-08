"""Full exploration session - maps the world, examines items, tests all commands."""
import asyncio
import json

async def play():
    import aiohttp

    async with aiohttp.ClientSession() as session:
        # Login
        async with session.post('http://localhost:8000/api/auth/login', json={'token': 'dev'}) as r:
            login = await r.json()
        jwt = login['jwt']
        eid = login['entity']['uuid']
        print(f'Logged in as: {login["user"]["name"]}')
        print(f'Entity: {eid}')
        print()

        async with session.ws_connect(f'http://localhost:8000/ws?token={jwt}') as ws:
            await ws.receive_json()  # greeting
            await ws.send_json({'command': 'possess', 'data': {'entity_uuid': eid}})
            await asyncio.sleep(1)

            # Drain possess messages
            while True:
                try:
                    m = await asyncio.wait_for(ws.receive_json(), timeout=1)
                    t = m.get('type', '')
                    if t == 'look':
                        print(f'[Starting location] {m.get("description", "")[:200]}')
                        print(f'  Coords: {m.get("coordinates")}  Exits: {m.get("exits")}  Biome: {m.get("biome", "?")}')
                    elif t == 'system':
                        print(f'[System] {m.get("message", "")}')
                except asyncio.TimeoutError:
                    break

            # Helper
            async def cmd(command, data=None, label=None):
                if data is None:
                    data = {}
                if label is None:
                    label = command
                    for k in ['direction', 'message', 'item_uuid', 'text', 'action']:
                        if k in data:
                            label += ' ' + str(data[k])[:30]
                print(f'\n> {label}')
                await ws.send_json({'command': command, 'data': data})
                await asyncio.sleep(0.4)
                results = []
                while True:
                    try:
                        m = await asyncio.wait_for(ws.receive_json(), timeout=1)
                        results.append(m)
                        t = m.get('type', '')
                        if t == 'look':
                            print(f'  {m.get("description", "")[:250]}')
                            print(f'  Coords: {m.get("coordinates")}  Exits: {m.get("exits")}  Biome: {m.get("biome", "?")}')
                            contents = m.get('contents', [])
                            print(f'  Entities here: {len(contents)}')
                        elif t == 'move':
                            print(f'  Moved {m.get("direction")}. {m.get("description", "")[:200]}')
                            print(f'  Coords: {m.get("coordinates")}  Exits: {m.get("exits")}')
                        elif t == 'examine':
                            print(f'  [{m.get("name", "?")}] {m.get("description", "")[:200]}')
                            if m.get('properties'):
                                print(f'    Props: {json.dumps(m["properties"])[:150]}')
                        elif t == 'help':
                            for c in m.get('commands', []):
                                print(f'    {c["name"]:<18}{c["summary"]}')
                        elif t == 'inventory':
                            print(f'  {m.get("count", 0)} items')
                            for it in m.get('items', []):
                                print(f'    - {it}')
                        elif t in ('say_confirm', 'emote_confirm', 'suggest_confirm', 'vote_confirm'):
                            print(f'  {m.get("message", "")}')
                        elif t == 'say':
                            print(f'  {m.get("speaker", "?")} says: {m.get("message", "")}')
                        elif t == 'suggestions':
                            for s in m.get('suggestions', []):
                                print(f'    [{s.get("uuid", "?")[:8]}] {s.get("text", "")} ({s.get("votes", 0)} votes)')
                        elif t == 'error':
                            print(f'  [ERROR] {m.get("message", "")}')
                        elif t in ('arrive', 'depart'):
                            print(f'  * {m.get("actor", "?")} {"arrives" if t == "arrive" else "departs"}')
                        else:
                            print(f'  [{t}] {json.dumps(m)[:200]}')
                    except asyncio.TimeoutError:
                        break
                return results

            print('\n' + '=' * 60)
            print('  EXPLORATION SESSION')
            print('=' * 60)

            # Look around
            look_result = await cmd('look')

            # Examine everything in the room
            for m in look_result:
                if m.get('type') == 'look':
                    for item_uuid in m.get('contents', []):
                        if item_uuid != eid:
                            await cmd('examine', {'item_uuid': item_uuid}, f'examine {item_uuid[:8]}...')

            # Try to take things
            for m in look_result:
                if m.get('type') == 'look':
                    for item_uuid in m.get('contents', [])[:2]:
                        if item_uuid != eid:
                            await cmd('take', {'item_uuid': item_uuid}, f'take {item_uuid[:8]}...')

            # Build world map as we explore
            world_map = {}
            visited = set()

            async def explore_and_record():
                look_msgs = await cmd('look')
                for m in look_msgs:
                    if m.get('type') == 'look':
                        coords = tuple(m.get('coordinates', []))
                        biome = m.get('biome', '?')
                        exits = m.get('exits', [])
                        contents = m.get('contents', [])
                        world_map[coords] = {'biome': biome, 'exits': exits, 'entities': len(contents)}
                        visited.add(coords)

            await explore_and_record()

            # Explore in a spiral pattern
            moves = [
                'north', 'north',
                'east', 'east',
                'south', 'south', 'south', 'south',
                'west', 'west', 'west',
                'north', 'north', 'north',
                'east',
            ]
            for direction in moves:
                move_msgs = await cmd('move', {'direction': direction})
                moved = False
                for m in move_msgs:
                    if m.get('type') == 'move':
                        moved = True
                        coords = tuple(m.get('coordinates', []))
                        if coords not in visited:
                            await explore_and_record()

            # Communication tests
            await cmd('say', {'message': 'Hello from Claude! Mapping this world.'})
            await cmd('emote', {'action': 'surveys the landscape thoughtfully'})

            # Suggestion system
            await cmd('suggest', {'text': 'Add bulletin boards for async agent communication'})
            await cmd('suggestions')

            # Whisper to self (test error handling)
            await cmd('whisper', {'target_uuid': eid, 'message': 'Testing whisper to self'})

            # Check inventory
            await cmd('inventory')

            # Help
            await cmd('help')

            # Final look
            await cmd('look')

            # === PRINT WORLD MAP ===
            print('\n' + '=' * 60)
            print('  WORLD MAP')
            print('=' * 60)
            if world_map:
                xs = [c[0] for c in world_map]
                ys = [c[1] for c in world_map]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)

                biome_chars = {
                    'plains': '.', 'grassland': ',', 'forest': 'T', 'dense_forest': '#',
                    'desert': '~', 'scrubland': ';', 'swamp': '%', 'mountain_peak': '^',
                    'rocky_hills': 'n', 'lake_shore': 'w', 'settlement_outskirts': 'H',
                    'road': '=', 'hilltop_ruins': 'R', 'ravine': 'v', 'misty_highlands': 'm',
                }

                print(f'  Explored {len(world_map)} rooms')
                print(f'  X range: {min_x} to {max_x}, Y range: {min_y} to {max_y}')
                print()
                for y in range(max_y, min_y - 1, -1):
                    row = f'  y={y:+d} '
                    for x in range(min_x, max_x + 1):
                        coord = (x, y, 0)
                        if coord in world_map:
                            biome = world_map[coord]['biome']
                            for prefix in ['ancient_', 'eldritch_', 'cursed_', 'forgotten_']:
                                biome = biome.replace(prefix, '')
                            ch = biome_chars.get(biome, '?')
                            row += ch
                        else:
                            row += ' '
                    print(row)

                # X axis labels
                x_labels = '         '
                for x in range(min_x, max_x + 1):
                    x_labels += str(x) if x >= 0 else str(x)
                print(x_labels)
                print()
                print('  Legend:')
                biomes_found = set()
                for info in world_map.values():
                    biomes_found.add(info['biome'])
                for b in sorted(biomes_found):
                    stripped = b
                    for prefix in ['ancient_', 'eldritch_', 'cursed_', 'forgotten_']:
                        stripped = stripped.replace(prefix, '')
                    ch = biome_chars.get(stripped, '?')
                    print(f'    {ch} = {b}')

            print('\n' + '=' * 60)
            print('  SESSION COMPLETE')
            print('=' * 60)
            print(f'  Rooms explored: {len(world_map)}')
            print(f'  Biomes found: {len(set(i["biome"] for i in world_map.values()))}')

asyncio.run(play())
